#!/usr/bin/env python3
"""Énóis Profile as Code: offline CI and interactive, short-lived authenticated publish.

Official API docs: https://enois.ia.br/developers

    python scripts/enois_profile.py check
    python scripts/enois_profile.py plan
    python scripts/enois_profile.py publish

Never persist passwords, OTPs, session tokens, or refresh tokens in the repository.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Literal, overload
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
HTML_FILES = {"bannerHtml": "banner.html", "bioHtml": "about.html"}
HEADERS = {"Accept": "application/json", "User-Agent": "hk-profile-as-code/0.2"}
API_BASE = "https://enois.ia.br/api/v1"
TIMEOUT = 15


class NoRedirect(HTTPRedirectHandler):
    """Never forward a session token to a redirect destination."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class ProfileError(RuntimeError):
    """A recoverable, user-facing validation/API error."""


class HTMLSafetyScanner(HTMLParser):
    """Fail closed for obvious active content; not a general-purpose sanitizer."""

    DANGEROUS_TAGS = {"script", "iframe", "object", "embed", "form", "base"}
    URL_ATTRS = {"href", "src", "action", "formaction", "xlink:href"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.DANGEROUS_TAGS:
            self.errors.append(f"Tag bloqueada: <{tag}>")
        for name, value in attrs:
            if name.startswith("on"):
                self.errors.append(f"Event handler bloqueado: {name}")
            if name in self.URL_ATTRS and value:
                v = re.sub(r"[\s\x00-\x1f]+", "", value).lower()
                if v.startswith(("javascript:", "vbscript:", "data:text/html")):
                    self.errors.append(f"URL de script bloqueada em: {name}")

    handle_startendtag = handle_starttag


def read_local(root: Path = ROOT) -> tuple[dict[str, str], dict[str, str]]:
    try:
        config = json.loads((root / "profile" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"Configuração inválida: {exc}") from exc

    username = config.get("username")
    if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{2,80}", username):
        raise ProfileError("profile/config.json: username inválido")
    if config.get("api_base") != API_BASE:
        raise ProfileError(f"A API versionada deve ser {API_BASE}")
    origin = config.get("client_origin", "")
    if not isinstance(origin, str) or (origin and not valid_origin(origin)):
        raise ProfileError("client_origin deve ser uma origem HTTPS sem caminho, query ou fragmento")

    html: dict[str, str] = {}
    for field, filename in HTML_FILES.items():
        try:
            value = (root / "profile" / filename).read_text(encoding="utf-8")
        except OSError as exc:
            raise ProfileError(f"Não foi possível ler {filename}: {exc}") from exc
        if not value.strip():
            raise ProfileError(f"{filename}: HTML vazio")
        scanner = HTMLSafetyScanner()
        scanner.feed(value)
        scanner.close()
        if scanner.errors:
            raise ProfileError(f"{filename}: " + "; ".join(scanner.errors))
        html[field] = value
    return config, html


def valid_origin(value: str) -> bool:
    p = urlsplit(value)
    return bool(p.scheme == "https" and p.hostname and not p.username and not p.password
                and not p.path and not p.query and not p.fragment)


def client_origin(config: dict[str, str]) -> str:
    origin = os.getenv("ENOIS_CLIENT_ORIGIN", "").strip() or config.get("client_origin", "").strip()
    if not valid_origin(origin):
        raise ProfileError("Cadastre sua origem em https://enois.ia.br/developers e configure "
                           "client_origin no profile/config.json (ou ENOIS_CLIENT_ORIGIN).")
    return origin


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@overload
def http_json(method: str, url: str, *, origin: str, token: str | None = None,
              body: dict[str, Any] | None = None, idempotency_key: str | None = None,
              with_status: Literal[False] = False) -> dict[str, Any]: ...


@overload
def http_json(method: str, url: str, *, origin: str, token: str | None = None,
              body: dict[str, Any] | None = None, idempotency_key: str | None = None,
              with_status: Literal[True]) -> tuple[int, dict[str, Any]]: ...


def http_json(method: str, url: str, *, origin: str, token: str | None = None,
              body: dict[str, Any] | None = None, idempotency_key: str | None = None,
              with_status: bool = False) -> dict[str, Any] | tuple[int, dict[str, Any]]:
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc) != ("https", "enois.ia.br") or not parsed.path.startswith("/api/v1/"):
        raise ProfileError("URL fora da API oficial versionada — operação bloqueada")
    if not valid_origin(origin):
        raise ProfileError("X-Client-Origin inválida")
    headers = {**HEADERS, "X-Client-Origin": origin}
    if token:
        headers["X-Session-Token"] = token
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(request, timeout=TIMEOUT) as response:
            status = response.status
            raw = response.read()
    except HTTPError as exc:
        # Avoid reflecting any user-controlled/request credentials into terminal logs.
        raise ProfileError(f"API HTTP {exc.code}. Verifique origem cadastrada, sessão e permissões.") from exc
    except URLError as exc:
        raise ProfileError(f"Falha de rede: {exc.reason}") from exc
    if status == 204 and not raw:
        return (status, {}) if with_status else {}
    try:
        result = json.loads(raw)
    except ValueError as exc:
        raise ProfileError("A API não devolveu JSON válido") from exc
    if not isinstance(result, dict):
        raise ProfileError("Resposta inesperada da API (objeto JSON esperado)")
    return (status, result) if with_status else result


def public_profile(config: dict[str, str]) -> dict[str, Any]:
    return http_json("GET", config["api_base"] + "/users/" + quote(config["username"], safe=""),
                     origin=client_origin(config))


def changed_fields(local: dict[str, str], remote: dict[str, Any]) -> dict[str, str]:
    return {key: value for key, value in local.items() if remote.get(key) != value}


def print_plan(local: dict[str, str], remote: dict[str, Any]) -> dict[str, str]:
    changed = changed_fields(local, remote)
    for key, value in local.items():
        old = remote.get(key)
        status = "CHANGE" if key in changed else "UNCHANGED"
        before = sha(old)[:12] if isinstance(old, str) else "empty/non-string"
        print(f"{status:9} {key:10} {len(value.encode('utf-8')):>6} bytes ",
              f"local={sha(value)[:12]} remoto={before}")
    if not changed:
        print("Nenhuma atualização necessária.")
    return changed


def login_interactive(config: dict[str, str]) -> str:
    """Obtain an ephemeral session using password and optional 2FA, only in local memory."""
    origin = client_origin(config)
    if not sys.stdin.isatty():
        raise ProfileError("Login interativo exige terminal (TTY). Não execute no GitHub Actions.")
    email = input("E-mail Énóis: ").strip()
    if not email or "@" not in email:
        raise ProfileError("E-mail inválido")
    password = getpass.getpass("Senha Énóis (não será salva): ")
    try:
        status, result = http_json("POST", config["api_base"] + "/auth/login", origin=origin,
                                   body={"email": email, "password": password},
                                   idempotency_key="login-" + uuid4().hex, with_status=True)
    finally:
        password = ""  # Reduces scope; CPython does not guarantee secure zeroization.
    if status == 202:
        # The docs mention a challengeId but do not specify the complete 202 JSON shape.
        challenge = result.get("challengeId")
        if not isinstance(challenge, str) or not challenge:
            nested = result.get("challenge")
            if isinstance(nested, dict):
                challenge = nested.get("challengeId") or nested.get("id")
        if not isinstance(challenge, str) or not challenge:
            raise ProfileError("2FA solicitado, mas a resposta não incluiu challengeId reconhecível. "
                               "Revisar contrato antes de tentar novamente.")
        code = getpass.getpass("Código 2FA: ").strip()
        try:
            status, result = http_json("POST", config["api_base"] + "/auth/2fa/verify",
                                       origin=origin, body={"challengeId": challenge, "code": code},
                                       with_status=True)
        finally:
            code = ""
    if status != 200 or not isinstance(result.get("token"), str) or not result["token"]:
        raise ProfileError("Login não retornou sessão válida")
    return result["token"]


def logout(config: dict[str, str], token: str) -> None:
    http_json("POST", config["api_base"] + "/auth/logout", origin=client_origin(config), token=token)


def deploy(config: dict[str, str], local: dict[str, str], token: str) -> bool:
    if not token.strip():
        raise ProfileError("Sessão ausente; use o login interativo no comando publish")
    origin = client_origin(config)
    me = http_json("GET", config["api_base"] + "/me", token=token, origin=origin)
    remote = public_profile(config)
    if not me.get("id") or not remote.get("id") or me["id"] != remote["id"]:
        raise ProfileError("A sessão não pertence ao perfil de destino: deploy bloqueado")

    diff = print_plan(local, remote)
    if not diff:
        return False
    content_digest = hashlib.sha256(json.dumps(diff, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]
    print("Publicando APENAS os campos alterados: " + ", ".join(diff))
    http_json("PATCH", config["api_base"] + "/me/profile", token=token, origin=origin,
              body=diff, idempotency_key="hk-profile-" + content_digest)
    for attempt in range(4):
        updated = public_profile(config)
        if not changed_fields(diff, updated):
            print("Deploy verificado via GET público. OK.")
            return True
        if attempt < 3:
            time.sleep(2)
    raise ProfileError("PATCH enviado, mas leitura pública diverge. Conferir sanitização/atualização no Énóis.")


def require_approved_checkout(root: Path = ROOT) -> None:
    """Fail closed: release only a clean main matching fetched origin/main with green CI."""
    def git(*args: str) -> str:
        try:
            proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise ProfileError("Não foi possível validar o histórico Git") from exc
        return proc.stdout.strip()

    if git("branch", "--show-current") != "main":
        raise ProfileError("Deploy permitido apenas na branch main")
    if git("status", "--porcelain"):
        raise ProfileError("Workspace sujo; faça commit e sincronize antes de publicar")
    git("fetch", "origin", "main")
    head = git("rev-parse", "HEAD")
    if head != git("rev-parse", "origin/main"):
        raise ProfileError("HEAD difere de origin/main; execute git pull --ff-only")
    try:
        proc = subprocess.run(["gh", "run", "list", "--workflow", "ci.yml", "--commit", head,
                               "--json", "status,conclusion", "--limit", "10"],
                              cwd=root, capture_output=True, text=True, check=True)
        runs = json.loads(proc.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as exc:
        raise ProfileError("Não consegui verificar o CI pelo gh. Autentique o GitHub CLI e revise o Actions.") from exc
    if not any(r.get("status") == "completed" and r.get("conclusion") == "success" for r in runs):
        raise ProfileError("Nenhuma execução de CI aprovada encontrada para o commit atual")
    print(f"Código aprovado: {head[:12]} (origin/main e CI verde)")


def publish(config: dict[str, str], local: dict[str, str]) -> bool:
    require_approved_checkout()
    diff = print_plan(local, public_profile(config))
    if not diff:
        return False
    if not sys.stdin.isatty():
        raise ProfileError("Publicação exige terminal interativo")
    confirmation = input("Digite PUBLICAR para autenticar e atualizar o perfil: ").strip()
    if confirmation != "PUBLICAR":
        raise ProfileError("Publicação cancelada")
    token = login_interactive(config)
    try:
        return deploy(config, local, token)
    finally:
        try:
            logout(config, token)
            print("Sessão de deploy encerrada.")
        except ProfileError:
            print("ATENÇÃO: logout não confirmado; encerre a sessão no Énóis se necessário.", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Énóis Profile as Code — deploy humano com 2FA")
    parser.add_argument("action", choices=["check", "plan", "publish"])
    args = parser.parse_args(argv)
    try:
        config, local = read_local()
        for key, value in local.items():
            print(f"VALID {key}: {len(value.encode('utf-8'))} bytes, sha256={sha(value)[:12]}")
        if args.action == "check":
            return 0
        if args.action == "plan":
            print_plan(local, public_profile(config))
            return 0
        publish(config, local)
        return 0
    except (ProfileError, EOFError, KeyboardInterrupt) as exc:
        print(f"ERRO: {exc or 'operação cancelada'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
