# Contrato de integração (Énóis)

Fonte: https://enois.ia.br/developers (consultado em outubro/2026)

A documentação oficial descreve:

- `GET /api/users/{username}` público, expõe `bannerHtml` e `bioHtml`.
- `GET /api/me` privado, requer `X-Session-Token` e permite comparar ID da conta com perfil público.
- `PATCH /api/me/profile` privado, aceita `bioHtml` e `bannerHtml`.
- `POST /api/auth/login`, com possível challenge de 2FA. OAuth e escopos específicos de integração ainda estão em construção.
- Alguns endpoints de escrita exigem `Idempotency-Key`. Enviamos a chave no PATCH por precaução, sem afirmar que ele exige esse header.

### Compatibilidade pendente de teste real

A documentação **não** define a estrutura completa da resposta do PATCH, prazo de expiração da sessão, máximos de caracteres nos campos HTML, sanitizador permitido ou prazo de consistência da leitura.

Por isso, o deploy:

1. valida o conteúdo e identifica mudanças com leitura pública;
2. valida se a sessão pertence ao perfil-alvo com o mesmo `id`;
3. envia **somente** `bannerHtml` e/ou `bioHtml` alterados;
4. lê novamente o perfil e só anuncia sucesso quando o HTML público coincide literalmente;
5. deixa os arquivos locais como fonte de verdade — não faz importação silenciosa de mudanças remotas.

Se o Énóis sanitizar ou normalizar a marcação, o PATCH pode ser aceito e o deploy indicar divergência. Comparar o HTML público com a versão local antes de tentar outra publicação.

### Política de automações

A documentação afirma que publicações automáticas de conteúdo por bots e integrações são proibidas, enquanto criar/agendar posts por funcionalidade oficial sob controle humano é permitido. Não há esclarecimento explícito sobre deploy automatizado de **campos do próprio perfil**. Este protótipo **não publica posts**, e o perfil só pode ser atualizado com comando humano explícito. Antes de disparar deploys automáticos no merge, solicitar confirmação à equipe do Énóis.

### Segurança

Não enviar credenciais a terceiros ou a este chat. Nunca versionar cookies, token de sessão, refresh token ou senha. Tokens de sessão expiram e possivelmente exigem renovação manual com 2FA. O workflow utiliza somente `ENOIS_SESSION_TOKEN` na etapa que efetivamente publica, depois de aprovação manual. Preferir um ambiente GitHub `production` com reviewers e restrição à branch `main`.

### HTTPS e redirecionamentos

As requisições só aceitam `https://enois.ia.br/api/...`. Redirecionamentos HTTP não são seguidos, para que o token de sessão jamais seja enviado inadvertidamente a outro host.
