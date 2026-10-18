#!/usr/bin/env python3
"""Profile as Code for Énóis. Stdlib only; deploy is always explicit.

Official API docs: https://enois.ia.br/developers

    python scripts/enois_profile.py check
    python scripts/enois_profile.py plan
    ENOIS_SESSION_TOKEN=... python scripts/enois_profile.py deploy --confirm PUBLICAR
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
HTML_FILES = {"bannerHtml": "banner.html", "bioHtml": "about.html"}
HEADERS = {"Accept": "application/json", "User-Agent": "hk-profile-as-code/0.1"}
TIMEOUT = 15


class NoRedirect(HTTPRedirectHandler):
    """Never forward a session token to redirect destinations."""

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
    config_path = root / "profile" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"Configuração inválida: {exc}") from exc

    username = config.get("username")
    base = config.get("api_base")
    if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{2,80}", username):
        raise ProfileError("profile/config.json: username inválido")
    if base != "https://enois.ia.br/api":
        raise ProfileError("API deve ser https://enois.ia.br/api (sem redirecionamento)")

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


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def http_json(method: str, url: str, *, token: str | None = None,
              body: dict[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc) != ("https", "enois.ia.br") or not parsed.path.startswith("/api/"):
        raise ProfileError("URL fora da API oficial — operação bloqueada")
    headers = dict(HEADERS)
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
            raw = response.read()
    except HTTPError as exc:
        raw = exc.read(4000)
        detail = raw.decode("utf-8", errors="replace")[:280]
        raise ProfileError(f"API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ProfileError(f"Falha de rede: {exc.reason}") from exc
    try:
        result = json.loads(raw)
    except ValueError as exc:
        raise ProfileError("A API não devolveu JSON válido") from exc
    if not isinstance(result, dict):
        raise ProfileError("Resposta inesperada da API (objeto JSON esperado)")
    return result


def public_profile(config: dict[str, str]) -> dict[str, Any]:
    return http_json("GET", config["api_base"] + "/users/" + quote(config["username"], safe=""))


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


def deploy(config: dict[str, str], local: dict[str, str], token: str) -> bool:
    if not token.strip():
        raise ProfileError("ENOIS_SESSION_TOKEN ausente (não usar login/senha no CI)")
    me = http_json("GET", config["api_base"] + "/me", token=token)
    remote = public_profile(config)
    # Verify session belongs to the public profile being modified.
    if not me.get("id") or not remote.get("id") or me["id"] != remote["id"]:
        raise ProfileError("A sessão não pertence ao perfil de destino: deploy bloqueado")

    diff = print_plan(local, remote)
    if not diff:
        return False
    # A stable key makes retries for a given payload idempotent when supported.
    content_digest = hashlib.sha256(json.dumps(diff, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]
    print("Publicando APENAS os campos alterados: " + ", ".join(diff))
    http_json("PATCH", config["api_base"] + "/me/profile", token=token,
              body=diff, idempotency_key="hk-profile-" + content_digest)
    # Verify read-after-write; do not say success if sanitizer or API changed HTML.
    for attempt in range(4):
        updated = public_profile(config)
        if not changed_fields(diff, updated):
            print("Deploy verificado via GET público. OK.")
            return True
        if attempt < 3:
            time.sleep(2)
    raise ProfileError("PATCH enviado, mas leitura pública diverge. Conferir sanitização/atualização no Énóis.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Perfil Énóis como código (sem deploy automático)")
    parser.add_argument("action", choices=["check", "plan", "deploy"])
    parser.add_argument("--confirm", default="", help="Digite PUBLICAR para permitir PATCH")
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
        if args.confirm != "PUBLICAR":
            raise ProfileError("Deploy exige confirmação explícita: --confirm PUBLICAR")
        deploy(config, local, os.getenv("ENOIS_SESSION_TOKEN", ""))
        return 0
    except ProfileError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
