# Engineering Lab · Profile as Code

Hugo Kersbaumer — do desenho mecânico à arquitetura de sistemas. O código em `profile/` é a fonte de verdade para o banner e o Sobre no Énóis.

## Arquitetura

```text
GitHub PR → CI (check + tests) → merge main
                               ↓
             dev01: git pull → publish interativo
                               ↓
            GET público → revisão humana → login + 2FA
                               ↓
            valida conta → PATCH alterados → GET → logout
```

**O GitHub não guarda sessões, senha, OTP ou refresh token.** O job `deploy.yml` foi convertido em uma prévia **somente leitura**; o deploy acontece no terminal do usuário com sessão obtida na hora. O CLI requer a `main` limpa, sincronizada com `origin/main`, e uma execução verde de `ci.yml` para o mesmo SHA.

Não há aplicação backend, Docker, Terraform, JavaScript ou dependências Python adicionais.

## 1. Cadastrar origem do cliente

A API atual exige `X-Client-Origin` em **todas** as requisições. Abra https://enois.ia.br/developers, entre com sua conta e cadastre a origem HTTPS do aplicativo, conforme as regras do portal. Coloque **exatamente** essa origem no `profile/config.json`:

```json
{
  "username": "hugo-kersbaumer",
  "api_base": "https://enois.ia.br/api/v1",
  "client_origin": "https://ORIGEM-QUE-VOCE-CADASTROU.EXAMPLE"
}
```

`client_origin` é configuração pública, **não** segredo. Para experimentar sem alterar o arquivo, use `ENOIS_CLIENT_ORIGIN=https://...` no ambiente. Não copie nem use a origem interna do Énóis fingindo ser o frontend oficial.

## 2. Validar no Debian

```bash
cd ~/projects/enois-profile-as-code
python3 scripts/enois_profile.py check
python3 -m unittest discover -s tests -v
python3 scripts/enois_profile.py plan  # rede; somente leitura
```

Os checks e testes unitários são offline. `plan` consulta o perfil via GET e exige uma origem já registrada.

## 3. Publicar o commit aprovado

Após merge de um PR com CI verde:

```bash
git switch main
git pull --ff-only
python3 scripts/enois_profile.py publish
```

O comando confere branch, workspace limpo, igualdade com `origin/main` e CI verde **do mesmo commit** (requer `gh` instalado e autenticado). Mostra o diff sem token e pede a confirmação `PUBLICAR`. Então solicita e-mail, senha e, caso o login retorne um desafio HTTP 202, o código 2FA. Usa a sessão apenas em memória, valida que o ID da conta é o mesmo do perfil e publica apenas `bioHtml` e/ou `bannerHtml` alterados. Tenta verificar o conteúdo publicado e faz logout mesmo se o deploy falhar.

**Observação:** a documentação da API não detalha o JSON de resposta HTTP 202; o cliente procura `challengeId` no nível superior ou dentro de `challenge`. Se o provedor usar outro formato, falha sem publicar. Uma sessão e seu refresh token nunca são impressos ou persistidos por este programa. Mesmo após logout, o sistema operacional pode manter fragmentos na memória até encerramento do processo.

## 4. Preview remoto opcional

Em GitHub → Actions → `Preview Énóis profile drift (read-only)` você pode rodar comparação remota, mas antes configure `ENOIS_CLIENT_ORIGIN` em **Settings → Secrets and variables → Actions → Variables**. Este workflow **não** faz login, não recebe token, e nunca realiza PATCH. Não há `ENOIS_SESSION_TOKEN` a cadastrar.

## Segurança e limites

- Publicação só com confirmação humana e credenciais digitadas localmente.
- Não envie credenciais por chat, CLI flags, logs, workflow_dispatch inputs ou commits.
- Validação local de HTML rejeita script, iframe, handlers inline e URLs JavaScript; isso **não substitui** a sanitização feita pelo Énóis.
- O HTML remoto pode ser normalizado pela API e causar divergência após PATCH. Compare o resultado publicado antes de repetir.
- Não existe rollback automático; revert do Git + novo `publish` restaura o conteúdo anterior.
- A documentação pública não esclarece se alterações automatizadas de campos do próprio perfil entram na restrição a publicação de conteúdo por bots. O fluxo mantém autorização humana explícita. Antes de implementar CD autônomo, confirme as regras com a equipe Énóis.

Consulte [docs/CONTRATO-API.md](docs/CONTRATO-API.md) para detalhes da API.
