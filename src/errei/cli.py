"""Interface de linha de comando (pt-BR)."""

from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import typer

from errei import __version__
from errei.config import PROJECT_CONFIG, TEMPLATE, Config, ConfigError
from errei.project import ProjectError

app = typer.Typer(
    name="errei",
    help="Audita um artigo científico em LaTeX (pt-BR): estrutura, referências, ABNT, "
    "escrita, similaridade, indícios de IA e prontidão para periódicos.",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)

SUBCOMMANDS = {"audit", "init", "doctor", "explain", "modelo", "cache"}


class OutFormat(str, Enum):
    term = "term"
    md = "md"
    json = "json"
    pdf = "pdf"


class NivelAlvo(str, Enum):
    tcc = "tcc"
    mestrado = "mestrado"
    doutorado = "doutorado"
    a1 = "a1"


class FailOn(str, Enum):
    error = "error"
    warning = "warning"
    never = "never"


def _err(msg: str) -> None:
    typer.echo(f"errei: {msg}", err=True)


def _csv(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out += [x.strip() for x in v.split(",") if x.strip()]
    return out


@app.command("audit", help="Audita a pasta de um artigo LaTeX (padrão: pasta atual).")
def audit(
    path: Annotated[Path, typer.Argument(help="Pasta do artigo.")] = Path(),
    online: Annotated[
        bool | None,
        typer.Option(
            "--online/--offline", help="Habilita checagens que usam rede (padrão: desligado)."
        ),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Roda só estes verificadores (ex.: abnt,refs)."),
    ] = None,
    skip: Annotated[list[str] | None, typer.Option("--skip", help="Pula verificadores.")] = None,
    fmt: Annotated[OutFormat, typer.Option("--format", "-f", help="Formato da saída.")] = (
        OutFormat.term
    ),
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Grava o relatório neste arquivo.")
    ] = None,
    fail_on: Annotated[
        FailOn | None, typer.Option("--fail-on", help="Quando sair com código 1.")
    ] = None,
    qualis_csv: Annotated[
        Path | None,
        typer.Option("--qualis-csv", help="CSV do Qualis exportado da Plataforma Sucupira."),
    ] = None,
    qualis_data: Annotated[
        str | None, typer.Option("--qualis-data", help="Data de referência do CSV (AAAA-MM-DD).")
    ] = None,
    periodico: Annotated[
        str | None, typer.Option("--periodico", help='Periódico-alvo: "ISSN 1234-5678" ou título.')
    ] = None,
    area: Annotated[str | None, typer.Option("--area", help="Área de avaliação CAPES.")] = None,
    email: Annotated[
        str | None, typer.Option("--email", help="E-mail para o polite pool do Crossref/OpenAlex.")
    ] = None,
    main_tex: Annotated[str | None, typer.Option("--main", help="Arquivo .tex principal.")] = None,
    jobs: Annotated[int | None, typer.Option("--jobs", "-j", help="Threads.")] = None,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Só erros e avisos no terminal.")
    ] = False,
    color: Annotated[bool | None, typer.Option("--color/--no-color")] = None,
    no_user_config: Annotated[
        bool, typer.Option("--no-user-config", help="Ignora ~/.config/errei/config.toml.")
    ] = False,
    pdf: Annotated[
        Path | None,
        typer.Option("--pdf", help="Grava também um relatório PDF neste arquivo."),
    ] = None,
    resumo: Annotated[
        bool,
        typer.Option("--resumo", help="Na tela, só os principais problemas e melhorias."),
    ] = False,
    sem_cache: Annotated[
        bool,
        typer.Option(
            "--sem-cache",
            help="Com --online, ignora o cache e consulta as fontes de novo (o resultado "
            "novo é gravado no cache).",
        ),
    ] = False,
    texto_completo: Annotated[
        bool,
        typer.Option(
            "--texto-completo",
            help="Com --online, baixa PDFs de acesso aberto das obras citadas para conferir "
            "citações diretas.",
        ),
    ] = False,
    tipo: Annotated[
        str | None,
        typer.Option(
            "--tipo",
            help="Tipo do trabalho para a completude: artigo, monografia, tcc, dissertacao, "
            "tese (padrão: detectar).",
        ),
    ] = None,
    ia_online: Annotated[
        bool,
        typer.Option(
            "--ia-online",
            help="Com --online, usa o Google Gemini para sugerir consultas, obras nacionais "
            "(sempre conferidas em bases abertas) e orientações. ENVIA trechos do trabalho ao "
            "Google. Chave em GEMINI_API_KEY. A IA nunca escreve no trabalho.",
        ),
    ] = False,
    todo: Annotated[
        Path | None,
        typer.Option(
            "--todo",
            help="Grava a lista de afazeres (Markdown) neste arquivo. Com --pdf, é gerada "
            "automaticamente ao lado do PDF (<nome>-afazeres.md).",
        ),
    ] = None,
    nivel: Annotated[
        NivelAlvo | None,
        typer.Option(
            "--nivel",
            help="Nível que o trabalho deve alcançar na lista de afazeres: tcc, mestrado, "
            "doutorado ou a1 (Scopus percentil ≥ 92 / Qualis A1–A2; padrão).",
        ),
    ] = None,
    ia_modelo: Annotated[
        str | None,
        typer.Option("--ia-modelo", help="Modelo Gemini (padrão: gemini-flash-lite-latest)."),
    ] = None,
) -> None:
    overrides: dict[str, Any] = {}
    if tipo:
        overrides["completude"] = {"tipo": tipo}
    if nivel is not None:
        overrides["todo"] = {"nivel": nivel.value}
    if ia_online:
        overrides["ia_online"] = {"enabled": True}
        if ia_modelo:
            overrides["ia_online"]["modelo"] = ia_modelo
    if texto_completo:
        overrides["refs"] = {"texto_completo": True}
    if sem_cache:
        overrides["sem_cache"] = True
    if online is not None:
        overrides["online"] = online
    if email:
        overrides["email"] = email
    if main_tex:
        overrides["main"] = main_tex
    if jobs is not None:
        overrides["jobs"] = jobs
    if fail_on is not None:
        overrides["fail_on"] = fail_on.value
    if only or skip:
        overrides["checkers"] = {}
        if only:
            overrides["checkers"]["only"] = _csv(only)
        if skip:
            overrides["checkers"]["skip"] = _csv(skip)
    per: dict[str, Any] = {}
    if qualis_csv is not None:
        per["qualis_csv"] = str(qualis_csv.expanduser())
    if qualis_data:
        per["qualis_data"] = qualis_data
    if periodico:
        per["periodico"] = periodico
    if area:
        per["area"] = area
    if per:
        overrides["periodico"] = per

    from errei import pipeline

    try:
        config = Config.load(path, overrides, use_user_config=not no_user_config)
        flags = {
            "online": config.online,
            "only": _csv(only),
            "skip": _csv(skip),
            "format": fmt.value,
            "fail_on": config.data.get("fail_on"),
            "qualis_csv": per.get("qualis_csv"),
            "periodico": per.get("periodico"),
            "pdf": str(pdf) if pdf else None,
            "texto_completo": texto_completo,
            "sem_cache": sem_cache,
            "tipo": tipo,
            "ia_online": ia_online,
            "nivel": str(config.get("todo", "nivel", "a1")),
        }
        if ia_online and not config.online:
            raise ConfigError("--ia-online requer --online (a IA roda em servidor externo)")
        report = _run_with_progress(pipeline, path, config, flags, quiet=quiet)
    except (ProjectError, ConfigError, ValueError) as exc:
        _err(str(exc))
        raise typer.Exit(2) from exc

    from errei.report import render

    pdf_target = pdf
    if fmt is OutFormat.pdf:
        pdf_target = out or Path("errei-relatorio.pdf")
    if pdf_target is not None:
        from errei.report.pdf import PdfUnavailableError, write_pdf

        try:
            write_pdf(report, pdf_target)
        except PdfUnavailableError as exc:
            _err(str(exc))
            raise typer.Exit(2) from exc
        except OSError as exc:
            _err(f"não foi possível gravar {pdf_target}: {exc}")
            raise typer.Exit(2) from exc
        typer.echo(f"relatório PDF gravado em {pdf_target}", err=True)
    todo_target = todo
    if todo_target is None and pdf_target is not None:
        todo_target = pdf_target.with_name(pdf_target.stem + "-afazeres.md")
    if todo_target is not None:
        from errei.report import todo as todo_mod

        nivel_key = str(config.get("todo", "nivel", "a1") or "a1")
        if nivel_key not in todo_mod.NIVEIS:
            _err(f"nível desconhecido: {nivel_key} (use tcc, mestrado, doutorado ou a1)")
            raise typer.Exit(2)
        try:
            todo_mod.write(report, todo_target, nivel_key)
        except (OSError, ValueError) as exc:
            _err(f"não foi possível gravar {todo_target}: {exc}")
            raise typer.Exit(2) from exc
        typer.echo(
            f"lista de afazeres ({todo_mod.NIVEIS[nivel_key].nome}) gravada em {todo_target}",
            err=True,
        )
    if fmt is OutFormat.pdf:
        # PDF como formato principal: mostra o resumo na tela também
        render.render_term(report, render.make_console(force_color=color), summary_only=True)
        raise typer.Exit(report.exit_code(str(config.data.get("fail_on", "error"))))

    if fmt is OutFormat.json:
        text = render.to_json(report)
    elif fmt is OutFormat.md:
        text = render.to_markdown(report)
    else:
        text = ""
    if out is not None:
        if fmt is OutFormat.term:
            text = render.to_term_string(report, color=False)
        try:
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            _err(f"não foi possível gravar {out}: {exc}")
            raise typer.Exit(2) from exc
        typer.echo(f"relatório gravado em {out}", err=True)
    elif fmt is OutFormat.term:
        render.render_term(
            report, render.make_console(force_color=color), quiet=quiet, summary_only=resumo
        )
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    raise typer.Exit(report.exit_code(str(config.data.get("fail_on", "error"))))


def _run_with_progress(
    pipeline: Any, path: Path, config: Config, flags: dict[str, Any], *, quiet: bool
) -> Any:
    """Roda o pipeline mostrando o progresso no stderr (só em terminal interativo)."""
    if quiet or not sys.stderr.isatty() or os.environ.get("ERREI_NO_PROGRESS"):
        return pipeline.run(path, config, flags=flags)
    from rich.console import Console

    console = Console(stderr=True, highlight=False)
    with console.status("analisando o artigo…") as status:

        def show(msg: str) -> None:
            status.update(msg)

        return pipeline.run(path, config, flags=flags, progress=show)


@app.command("init", help=f"Cria {PROJECT_CONFIG} comentado na pasta.")
def init(
    path: Annotated[Path, typer.Argument(help="Pasta do artigo.")] = Path(),
    force: Annotated[bool, typer.Option("--force", help="Sobrescreve se existir.")] = False,
) -> None:
    target = path / PROJECT_CONFIG
    if not path.is_dir():
        _err(f"pasta não encontrada: {path}")
        raise typer.Exit(2)
    if target.exists() and not force:
        _err(f"{target} já existe (use --force para sobrescrever)")
        raise typer.Exit(2)
    target.write_text(TEMPLATE, encoding="utf-8")
    typer.echo(f"criado {target}")


@app.command("doctor", help="Verifica dependências (Java, LanguageTool, hunspell, extras).")
def doctor(
    download: Annotated[
        bool, typer.Option("--download", help="Baixa o servidor LanguageTool se faltar (~250 MB).")
    ] = False,
    online: Annotated[
        bool, typer.Option("--online", help="Testa conectividade com as APIs.")
    ] = False,
) -> None:
    from errei.doctor import run_doctor

    raise typer.Exit(run_doctor(download=download, online=online))


@app.command("explain", help="Explica uma regra (ex.: errei explain ABNT-REF-012).")
def explain(
    code: Annotated[str | None, typer.Argument(help="Código da regra.")] = None,
    list_all: Annotated[bool, typer.Option("--list", help="Lista todas as regras.")] = False,
) -> None:
    from errei import rules
    from errei.registry import discover

    discover()  # importa os verificadores e registra as regras
    if list_all or not code:
        for r in rules.all_rules():
            mark = " (heurística)" if r.heuristic else ""
            typer.echo(f"{r.code:<22} {r.severity.value:<9} {r.title}{mark}")
        return
    rule = rules.get(code)
    if rule is None:
        _err(f"regra desconhecida: {code} (veja errei explain --list)")
        raise typer.Exit(2)
    typer.echo(f"{rule.code} — {rule.title}")
    typer.echo(f"severidade padrão: {rule.severity.value}")
    if rule.heuristic:
        typer.echo("tipo: heurística (aproximada; pode ter falsos positivos/negativos)")
    if rule.reference:
        typer.echo(f"referência: {rule.reference}")
    typer.echo("")
    typer.echo(rule.explanation)


modelo_app = typer.Typer(help="Gerencia os modelos locais (errei-cita, errei-resumo).")
app.add_typer(modelo_app, name="modelo")


@modelo_app.command("info", help="Mostra onde cada modelo está e suas métricas de avaliação.")
def modelo_info() -> None:
    import json as _json

    from errei import citecheck, resumocheck
    from errei.modelo_dist import DESCRICAO

    for mod in (citecheck, resumocheck):
        d = mod.model_dir()
        reason = mod.unavailable_reason()
        typer.echo(f"modelo: {mod.MODEL_NAME} — {DESCRICAO[mod.MODEL_NAME]}")
        typer.echo(f"  pasta:  {d}")
        typer.echo(f"  estado: {'pronto' if reason is None else reason}")
        card = d / "errei_avaliacao.json"
        if card.is_file():
            data = _json.loads(card.read_text(encoding="utf-8"))
            for lg in ("en", "pt"):
                r = data.get(f"afirmacao_{lg}", {})
                if r:
                    typer.echo(
                        f"  teste (afirmação em {lg}): acurácia {r['acuracia']:.3f}, "
                        f"F1 macro {r['f1_macro']:.3f}"
                    )
        card = d / "errei_resumo.json"
        if card.is_file():
            data = _json.loads(card.read_text(encoding="utf-8"))
            for lg in ("en", "pt"):
                r = (data.get("teste", {}).get(lg) or {}).get("modelo", {}).get("f1", {})
                if r:
                    typer.echo(
                        f"  teste ({lg}): F1 macro {r['macro']:.3f}, acurácia {r['acuracia']:.3f}"
                    )
        if (d / "README.md").is_file():
            typer.echo(f"  cartão do modelo: {d / 'README.md'}")


NomeOpt = Annotated[
    str | None,
    typer.Option("--nome", help="errei-cita-v1 ou errei-resumo-v1 (padrão: todos)."),
]


@modelo_app.command("baixar", help="Baixa os modelos publicados nas releases do GitHub.")
def modelo_baixar(
    versao: Annotated[
        str | None, typer.Option("--versao", help="Tag da release (padrão: 'modelos').")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Substitui o instalado.")] = False,
    nome: NomeOpt = None,
) -> None:
    from errei.modelo_dist import MODELOS, ModelDownloadError, baixar

    nomes = [nome] if nome else list(MODELOS)
    falhas = 0
    for n in nomes:
        try:
            dest = baixar(versao, force=force, nome=n)
        except ModelDownloadError as exc:
            _err(f"{n}: {exc}")
            falhas += 1
            continue
        typer.echo(f"{n} instalado em {dest}")
    if falhas:
        raise typer.Exit(2)


@modelo_app.command("instalar", help="Copia um modelo treinado (pasta) para o local padrão.")
def modelo_instalar(
    origem: Annotated[Path, typer.Argument(help="Pasta com config.json e pesos.")],
    force: Annotated[bool, typer.Option("--force", help="Substitui o instalado.")] = False,
    nome: Annotated[
        str, typer.Option("--nome", help="errei-cita-v1 (padrão) ou errei-resumo-v1.")
    ] = "errei-cita-v1",
) -> None:
    import shutil

    from errei.modelo_dist import MODELOS

    if nome not in MODELOS:
        _err(f"modelo desconhecido: {nome} (opções: {', '.join(MODELOS)})")
        raise typer.Exit(2)
    if not (origem / "config.json").is_file():
        _err(f"{origem} não parece um modelo (falta config.json)")
        raise typer.Exit(2)
    dest = MODELOS[nome]()
    if dest.exists():
        if not force:
            _err(f"{dest} já existe (use --force)")
            raise typer.Exit(2)
        shutil.rmtree(dest)
    shutil.copytree(origem, dest)
    typer.echo(f"modelo instalado em {dest}")


cache_app = typer.Typer(help="Cache das consultas online (~/.cache/errei).")
app.add_typer(cache_app, name="cache")


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


@cache_app.command("info", help="Mostra o tamanho e o conteúdo do cache das consultas online.")
def cache_info() -> None:
    from datetime import datetime

    from errei.config import cache_dir
    from errei.net import cache as cache_mod

    st = cache_mod.stats(cache_dir())

    def quando(ts: float | None) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"

    typer.echo(f"pasta:      {st['pasta']}")
    typer.echo(
        f"respostas:  {st['respostas']} ({_mb(st['http_bytes'])}) · "
        f'{st["nao_encontradas"]} "não encontrada" · {st["vencidas"]} vencida(s)'
    )
    typer.echo(f"período:    {quando(st['mais_antiga'])} → {quando(st['mais_recente'])}")
    for host, n in list(st["por_fonte"].items())[:10]:
        typer.echo(f"  {host:<40} {n}")
    typer.echo(f"PDFs:       {st['pdfs']} ({_mb(st['pdf_bytes'])})")
    typer.echo(
        f'validade:   respostas {cache_mod.DEFAULT_TTL // 86400} dias · "não encontrada" '
        f"{cache_mod.NEGATIVE_TTL // 86400} dias · PDFs {cache_mod.PDF_TTL // 86400} dias "
        f"(até {cache_mod.PDF_MAX_BYTES // 1024 // 1024} MB)"
    )


@cache_app.command("limpar", help="Apaga o cache das consultas online (não mexe nos modelos).")
def cache_limpar(
    vencidos: Annotated[
        bool, typer.Option("--vencidos", help="Apaga só as entradas vencidas.")
    ] = False,
) -> None:
    from errei.config import cache_dir
    from errei.net import cache as cache_mod

    res = cache_mod.clear(cache_dir(), somente_vencidos=vencidos)
    what = "vencidas " if vencidos else ""
    typer.echo(f"apagadas {res['respostas']} resposta(s) {what}e {res['pdfs']} PDF(s) do cache")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Mostra a versão.")] = False,
) -> None:
    if version:
        typer.echo(f"errei {__version__}")
        raise typer.Exit(0)


def _rewrite_argv(argv: list[str]) -> list[str]:
    """``errei .`` → ``errei audit .`` (comando padrão)."""
    if not argv:
        return ["audit"]
    first = argv[0]
    if first in SUBCOMMANDS or first in ("-h", "--help", "--version"):
        return argv
    return ["audit", *argv]


def main(argv: list[str] | None = None) -> None:
    args = _rewrite_argv(list(sys.argv[1:] if argv is None else argv))
    app(args=args, prog_name="errei")


if __name__ == "__main__":  # pragma: no cover
    main()
