-- Banco de treino do errei (SQLite). Versão do esquema em meta('esquema').
-- Texto (resumos, seções) só de obras com licença aberta que permite uso comercial;
-- metadados vêm do OpenAlex (CC0). Classificações (Qualis, Scopus, WoS) são por ISSN.

CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);

CREATE TABLE IF NOT EXISTS fontes (
  id TEXT PRIMARY KEY,                -- OpenAlex S...
  nome TEXT,
  issn_l TEXT,
  issns TEXT,                         -- JSON: ISSNs normalizados (8 caracteres)
  editora TEXT,
  pais TEXT,
  tipo TEXT,
  is_oa INTEGER, is_in_doaj INTEGER, is_in_scielo INTEGER, is_core INTEGER,
  listas TEXT,                        -- JSON: listed_in do OpenAlex (doaj, scielo, medline...)
  h_index INTEGER,
  media_citacoes_2a REAL,
  atualizado TEXT
);

CREATE TABLE IF NOT EXISTS issn_fonte (
  issn TEXT NOT NULL,
  fonte_id TEXT NOT NULL,
  PRIMARY KEY (issn, fonte_id)
);
CREATE INDEX IF NOT EXISTS ix_issn_fonte_fonte ON issn_fonte (fonte_id);

CREATE TABLE IF NOT EXISTS obras (
  id TEXT PRIMARY KEY,                -- OpenAlex W... ou 'scielo:<PID>'
  doi TEXT,
  pid_scielo TEXT,
  pmcid TEXT,
  titulo TEXT,
  idioma TEXT,
  ano INTEGER,
  tipo TEXT,
  fonte_id TEXT,
  licenca TEXT,                       -- normalizada: cc-by, cc0, public-domain...
  url_oa TEXT,
  pdf_url TEXT,
  volume TEXT, numero TEXT, pagina_ini TEXT, pagina_fim TEXT,
  editora TEXT,
  citacoes INTEGER,
  percentil_citacoes REAL,            -- citation_normalized_percentile do OpenAlex
  top10 INTEGER,
  dominio TEXT, campo TEXT, subcampo TEXT, topico TEXT,
  origem TEXT,                        -- openalex | scielo | ...
  coletado TEXT
);
CREATE INDEX IF NOT EXISTS ix_obras_doi ON obras (doi);
CREATE INDEX IF NOT EXISTS ix_obras_pid ON obras (pid_scielo);
CREATE INDEX IF NOT EXISTS ix_obras_fonte ON obras (fonte_id);
CREATE INDEX IF NOT EXISTS ix_obras_idioma_ano ON obras (idioma, ano);
CREATE INDEX IF NOT EXISTS ix_obras_campo ON obras (campo);

CREATE TABLE IF NOT EXISTS autores (
  obra_id TEXT NOT NULL, ordem INTEGER NOT NULL, nome TEXT,
  PRIMARY KEY (obra_id, ordem)
);

CREATE TABLE IF NOT EXISTS titulos (
  obra_id TEXT NOT NULL, lingua TEXT NOT NULL, texto TEXT, origem TEXT,
  PRIMARY KEY (obra_id, lingua)
);

CREATE TABLE IF NOT EXISTS resumos (
  obra_id TEXT NOT NULL, lingua TEXT NOT NULL, texto TEXT,
  estruturado INTEGER DEFAULT 0, origem TEXT,
  PRIMARY KEY (obra_id, lingua)
);

CREATE TABLE IF NOT EXISTS palavras_chave (
  obra_id TEXT NOT NULL, lingua TEXT NOT NULL, termo TEXT NOT NULL, ordem INTEGER, origem TEXT,
  PRIMARY KEY (obra_id, lingua, termo)
);

CREATE TABLE IF NOT EXISTS secoes (
  obra_id TEXT NOT NULL, lingua TEXT NOT NULL, ordem INTEGER NOT NULL,
  nivel INTEGER, titulo TEXT, tipo TEXT, parte TEXT, texto TEXT, origem TEXT,
  PRIMARY KEY (obra_id, lingua, ordem)
);
CREATE INDEX IF NOT EXISTS ix_secoes_tipo ON secoes (tipo);

CREATE TABLE IF NOT EXISTS referencias (
  obra_id TEXT NOT NULL, ordem INTEGER NOT NULL, texto TEXT,
  PRIMARY KEY (obra_id, ordem)
);

-- Qualis (sistema 'qualis', valor = estrato, area = área de avaliação), Scopus ('scopus':
-- indexada/inativa; 'scopus_citescore': valor = CiteScore, nota = percentil, area =
-- subárea), Web of Science ('wos': valor = SCIE/SSCI/AHCI/ESCI, area = categorias) e
-- listas abertas do OpenAlex ('openalex_lista': valor = doaj, scielo, cwts-core...).
CREATE TABLE IF NOT EXISTS classificacoes (
  issn TEXT NOT NULL,
  sistema TEXT NOT NULL,
  area TEXT NOT NULL DEFAULT '',
  valor TEXT,
  nota REAL,
  edicao TEXT NOT NULL DEFAULT '',
  titulo TEXT,
  origem TEXT,
  importado TEXT,
  PRIMARY KEY (issn, sistema, area, edicao)
);
CREATE INDEX IF NOT EXISTS ix_class_sistema ON classificacoes (sistema, valor);

CREATE TABLE IF NOT EXISTS textos_ia (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obra_id TEXT, lingua TEXT, tipo TEXT, modo TEXT,
  modelo TEXT, modelo_licenca TEXT, temperatura REAL, texto TEXT, gerado TEXT
);
CREATE INDEX IF NOT EXISTS ix_textos_ia_obra ON textos_ia (obra_id);

CREATE TABLE IF NOT EXISTS coletas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fonte TEXT, parametros TEXT, inicio TEXT, fim TEXT, novos INTEGER, estado TEXT
);

CREATE TABLE IF NOT EXISTS progresso (chave TEXT PRIMARY KEY, valor TEXT, atualizado TEXT);

-- o que já foi tentado (para retomar sem repetir): artigos do ArticleMeta e textos completos
CREATE TABLE IF NOT EXISTS scielo_vistos (pid TEXT PRIMARY KEY, estado TEXT, atualizado TEXT);
CREATE TABLE IF NOT EXISTS textos_vistos (obra_id TEXT PRIMARY KEY, estado TEXT, fonte TEXT, atualizado TEXT);

-- Classificação de cada revista e de cada obra (pelo ISSN da revista).
CREATE VIEW IF NOT EXISTS v_classificacao_fonte AS
SELECT f.id AS fonte_id, f.nome,
  (SELECT MIN(c.valor) FROM issn_fonte i JOIN classificacoes c
     ON c.issn = i.issn AND c.sistema = 'qualis' WHERE i.fonte_id = f.id) AS qualis_melhor,
  (SELECT COUNT(DISTINCT c.area) FROM issn_fonte i JOIN classificacoes c
     ON c.issn = i.issn AND c.sistema = 'qualis' WHERE i.fonte_id = f.id) AS qualis_areas,
  EXISTS (SELECT 1 FROM issn_fonte i JOIN classificacoes c
     ON c.issn = i.issn AND c.sistema = 'scopus' AND c.valor = 'indexada'
     WHERE i.fonte_id = f.id) AS scopus,
  (SELECT MAX(c.nota) FROM issn_fonte i JOIN classificacoes c
     ON c.issn = i.issn AND c.sistema = 'scopus_citescore' WHERE i.fonte_id = f.id) AS scopus_percentil,
  (SELECT GROUP_CONCAT(DISTINCT c.valor) FROM issn_fonte i JOIN classificacoes c
     ON c.issn = i.issn AND c.sistema = 'wos' WHERE i.fonte_id = f.id) AS wos_colecoes,
  f.is_in_doaj AS doaj, f.is_in_scielo AS scielo, f.is_core AS cwts_core, f.listas
FROM fontes f;

-- Cópia materializada da visão acima (consultas rápidas com milhões de obras).
-- Atualizada por classificar.py e coletar.py fontes (Banco.atualizar_classes).
CREATE TABLE IF NOT EXISTS fontes_classe (
  fonte_id TEXT PRIMARY KEY, nome TEXT, qualis_melhor TEXT, qualis_areas INTEGER,
  scopus INTEGER, scopus_percentil REAL, wos_colecoes TEXT,
  doaj INTEGER, scielo INTEGER, cwts_core INTEGER, listas TEXT
);

CREATE VIEW IF NOT EXISTS v_classificacao_obra AS
SELECT o.id AS obra_id, o.doi, o.titulo, o.ano, o.idioma, o.campo, o.licenca,
  c.nome AS revista, c.qualis_melhor, c.qualis_areas, c.scopus, c.scopus_percentil,
  c.wos_colecoes, c.doaj, c.scielo, c.cwts_core, o.percentil_citacoes, o.top10
FROM obras o LEFT JOIN fontes_classe c ON c.fonte_id = o.fonte_id;
