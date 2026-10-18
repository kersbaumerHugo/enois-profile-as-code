# Engineering Lab · Profile as Code

Hugo Kersbaumer — identidade técnica no Énóis. De engrenagens e cotas de engenharia para sistemas computacionais, mantendo uma porta aberta para trocar ideias.

**Git é a fonte de verdade.** HTML/CSS/SVG estão em `profile/`. Não há backend, Docker, Terraform, JavaScript ou dependências Python de terceiros.

## Arquitetura

```text
profile/banner.html + profile/about.html
       ↓  PR
GitHub Actions CI → HTML safety check + unittest
       ↓  merge main
manual workflow_dispatch (production, confirmação PUBLICAR)
       ↓
GET perfil → PATCH campos alterados → GET para verificar
       ↓
Perfil público no Énóis
```

## Rodar localmente (Debian)

```bash
python3 scripts/enois_profile.py check
python3 -m unittest discover -s tests -v
python3 scripts/enois_profile.py plan
```

`plan` precisa de rede para consultar o Énóis e é estritamente read-only. `check` e `unittest` são offline.

## Publicar com revisão humana

A documentação usa sessão de usuário no header `X-Session-Token` e pode pedir verificação em duas etapas. Não informe sua senha/token no chat e nunca coloque tokens no repositório.

Para publicar no próprio Debian com uma sessão válida **obtida pelo fluxo oficial de login**, no terminal:

```bash
read -rsp 'Token de sessão Énóis: ' ENOIS_SESSION_TOKEN; echo
export ENOIS_SESSION_TOKEN
python3 scripts/enois_profile.py plan
python3 scripts/enois_profile.py deploy --confirm PUBLICAR
unset ENOIS_SESSION_TOKEN
```

Para publicar via **GitHub Actions**:

1. Crie repositório privado ou público e envie os arquivos.
2. Settings → Environments → `production`. Configure aprovação manual e permita apenas a branch `main`.
3. No ambiente `production`, adicione o secret `ENOIS_SESSION_TOKEN` (sessão válida; pode expirar).
4. Actions → **Deploy Énóis profile (manual)** → Run workflow em `main`; digite `PUBLICAR`. O job valida e mostra diferenças antes de enviar o PATCH.
5. Confira o resultado no perfil público. O script também faz verificação por GET.

É normal o workflow falhar com 401 quando o token de sessão expirar; renove pelo login oficial, respeitando 2FA. **Não salve senha em GitHub Secrets para logar automaticamente** só para contornar isso.

## CI e segurança

- Deploy não roda em `push` e não publica posts de feed.
- Faz PATCH mínimo somente em `bioHtml` / `bannerHtml`.
- Confirma que a sessão pertence ao `id` do perfil de destino.
- Ignora mudanças não relacionadas a esses campos.
- Requer confirmação humana antes de editar a conta.
- Validação local rejeita `<script>`, eventos `on*`, `iframe` e URLs `javascript:`. Isso **não substitui** o sanitizador do Énóis.
- CSS tem seletores escopados a cada componente e respeita `prefers-reduced-motion`.

## Nota de compatibilidade

Ainda não realizamos deploy real; o comportamento de sanitização e os limites exatos de HTML do Énóis não estão detalhados na API pública. Veja [CONTRATO-API.md](docs/CONTRATO-API.md).
