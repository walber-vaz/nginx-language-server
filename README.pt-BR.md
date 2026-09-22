# Nginx Language Server

Um [Language Server](https://microsoft.github.io/language-server-protocol/) para `nginx.conf`.

_[Read in English](README.md)_

> **Fork mantido.** O projeto original,
> [pappasam/nginx-language-server](https://github.com/pappasam/nginx-language-server),
> de Sam Roeca, não é mais mantido. Este fork continua o desenvolvimento.

## Recursos

- **Autocompletar** diretivas válidas no bloco atual (`http`, `server`,
  `location`, `stream`, `mail`, `if` dentro de `location`...), `$variáveis`
  e snippets de blocos comuns (server HTTPS, proxy reverso, PHP-FPM...).
- **Hover** com a documentação de diretivas e variáveis, inclusive
  variáveis com prefixo como `$arg_page` ou `$http_user_agent`, a versão em
  que a diretiva surgiu, a indicação de NGINX Plus e o link para o nginx.org.
- **Diagnósticos** enquanto você digita: erros de sintaxe, diretivas
  desconhecidas e diretivas usadas onde o nginx não permite.
- **Outline** com os blocos `http` / `server` / `location` / `upstream`.
- **Ir para definição** em `include` (inclusive com glob) e de `proxy_pass`
  e das outras diretivas `*_pass` para o `upstream`; caminhos de `include`
  viram links clicáveis.
- **Formatação** que preserva comentários, linhas em branco e código Lua.

Tudo continua funcionando com o arquivo incompleto, e o servidor nunca lê
arquivos incluídos, a menos que você peça para ir até eles. Os dados das
diretivas são gerados a partir da documentação do nginx.org (nginx 1.31) e
atualizados mensalmente.

## Instalação

O servidor é distribuído pelo GitHub. Com [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/walber-vaz/nginx-language-server
```

ou com [pipx](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/walber-vaz/nginx-language-server
```

Cada [release no GitHub](https://github.com/walber-vaz/nginx-language-server/releases)
também traz o wheel pronto. Funciona com Python 3.10 a 3.14.

## Configuração no editor

A configuração para Neovim, coc.nvim e Helix está no
[README em inglês](README.md#editor-setup).

## Opções

As opções são enviadas em `initializationOptions`:

```json
{
  "diagnostics": {
    "enable": true,
    "unknownDirectives": true
  }
}
```

Use `unknownDirectives: false` para silenciar avisos de diretivas de
módulos de terceiros (OpenResty, Brotli...).

## Desenvolvimento

```bash
uv sync          # instala as dependências
make test        # ruff, pyright e pytest
make format      # formata o código
make data        # regenera os dados das diretivas a partir do nginx.org
```

Para lançar uma versão: atualize `version` no `pyproject.toml` e o
`CHANGELOG.md` e envie uma tag `vX.Y.Z`. O workflow de release gera o wheel
e publica a release no GitHub.

## Créditos

Escrito originalmente por Samuel Roeca. As primeiras versões dos dados das
diretivas vieram de
[hangxingliu/vscode-nginx-conf-hint](https://github.com/hangxingliu/vscode-nginx-conf-hint).
Licença GPL-3.0-only.
