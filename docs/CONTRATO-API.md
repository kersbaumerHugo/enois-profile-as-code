# Contrato de integração do Énóis

Fonte primária: https://enois.ia.br/developers (reconsultado em 27/10/2026).

## Endpoints usados

| Operação | Endpoint (`/api/v1`) | Sessão |
|---|---|---|
| Perfil público | `GET /users/{username}` | Não |
| Login | `POST /auth/login` | Não |
| Verificação 2FA | `POST /auth/2fa/verify` | Não |
| Conta atual | `GET /me` | Sim |
| Atualizar perfil | `PATCH /me/profile` | Sim |
| Logout | `POST /auth/logout` | Sim |

- Versão recomendada: `https://enois.ia.br/api/v1` (contrato público indica paridade com rotas sem versão).
- Toda requisição de integração precisa incluir `X-Client-Origin` com origem HTTPS cadastrada no painel de desenvolvedores. Não é token e não substitui login.
- Rotas autenticadas requerem `X-Session-Token`.
- `POST /auth/login` aceita `{"email":"...","password":"..."}`; com 2FA, retorna `202` e desafio. A documentação ainda não fornece exemplo completo do JSON `202`, somente menciona `challengeId`.
- `POST /auth/2fa/verify` recebe `{"challengeId":"...","code":"..."}` e devolve `token` e `refreshToken` em 200.
- Login direto sem 2FA retorna `token` e `refreshToken` em 200.
- `PATCH /me/profile` aceita `bannerHtml` e `bioHtml`; payload contém somente campos alterados.
- Requisições de escrita aceitam `Idempotency-Key`, obrigatório para algumas rotas. O cliente a usa no PATCH e no login.
- OAuth para integração de terceiros ainda não está disponível na documentação oficial.

## Regras de operação

1. GitHub Actions só executa testes/validação e prévia de leitura pública. Nunca recebe senha, TOTP, token ou refresh token.
2. No terminal do operador, `publish` exige commit de `main` alinhado com `origin/main` e resultado verde do CI para aquele SHA.
3. A prévia é mostrada antes do login; confirmação humana explícita impede publicação acidental.
4. A sessão é obtida interativamente com e-mail/senha e, se necessário, código 2FA.
5. `GET /me` e `GET /users/{username}` devem ter o mesmo ID. Caso contrário, abortar.
6. Depois do PATCH, `GET` público precisa corresponder ao HTML local, senão falhar com diagnóstico.
7. Sempre tentar logout no final, inclusive em caso de erro de deploy.

## Limites conhecidos

A documentação não informa com precisão o formato completo do desafio HTTP 202, prazo do token de sessão, limites de HTML, comportamento de normalização/sanitização nem consistência dos dados públicos após escrita. Sem testes autenticados na plataforma, o comportamento de ponta a ponta permanece pendente de validação.

A política proíbe publicação automática de conteúdo social por integrações, mas não diz expressamente se isso se aplica à atualização do banner/Sobre pelo próprio usuário. Este projeto não automatiza posts e preserva a confirmação humana antes de editar o perfil.
