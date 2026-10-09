# 🏗️ ERP de Gestão de Obras · PMO de Engenharia Civil

Aplicação web em **Python + Streamlit** para gestão de obra (PMO), pronta para o
**Streamlit Community Cloud** e responsiva (PC/celular). Vem com uma massa de simulação
completa de um **edifício residencial de 10 pavimentos** em Curitiba/PR
("Residencial Bosque das Araucárias").

Stack: Streamlit · Plotly · OpenCV · ReportLab · Graphviz · SQLite · Tesseract (OCR) · boto3 (S3) · ftplib (FTP) · Fernet (criptografia).

## Primeiro acesso

Na primeira execução o sistema abre **em branco**, pronto para cadastrar uma obra real, com um
único usuário: `admin`. A senha inicial é a definida em `ERP_ADMIN_PASSWORD` (Secrets/variável de
ambiente) ou, se não houver, a senha padrão `admin123`, que o sistema obriga a trocar no primeiro login.
A tela de login não exibe nenhuma senha.

Ordem sugerida de cadastro (cada formulário grava no banco na hora): Usuários → WBS/EAP →
Cronograma (tarefas, predecessoras, materiais, **Congelar baseline**) → Almoxarifado (materiais e
saldo inicial) → Agenda. No dia a dia: RDO, NFs, fotos e checklist ambiental.

**Projeto e Backup do Banco** (menu Administração):
- **Dados do projeto**: nome, local, início e custo indireto diário.
- **Banco no FTP / Backup**: configuração e teste do FTP (login + gravação), envio e restauração de versões.
- **Novo projeto**: apaga tudo (pede a palavra APAGAR) e recomeça; a versão anterior continua no histórico do FTP.
- **Carregar demonstração**: recria a simulação do edifício de 10 pavimentos para treinamento.

### Simulação de demonstração

Carregada pelo botão acima ou com `ERP_DEMO=1` na primeira execução. Usuários da simulação:
`admin/admin123`, `almoxarife/campo123`, `visualizador/visual123`, `fiscal.banco/Prov@2026`
(troca obrigatória), `eng.planejamento/plan2026`, `almox.noturno/campo456` (inativo).

## Banco de dados no FTP

O SQLite trabalha no disco do servidor do app e é copiado para `<pasta base>/backup-banco/` no FTP:

| Arquivo no FTP | Para quê |
|---|---|
| `erp_obra_latest.db` | última versão; restaurada automaticamente quando o app inicia vazio |
| `latest.json` | manifesto: versão, data, obra, nº de tarefas/RDOs/NFs, SHA-256 |
| `AAAA/MM/erp_obra_AAAAMMDD_HHMMSS.db` | histórico de versões (restauráveis pela tela) |

- O envio é automático após alterações (no máximo a cada 2 min) e é **conferido**: o arquivo é baixado
  de volta e comparado por SHA-256.
- **Proteção:** se o app reiniciar e não alcançar o FTP (endereço mudou), ele avisa o admin e **não**
  sobrescreve o backup bom com um banco vazio. Basta corrigir o endereço na tela, testar e restaurar.
- **Streamlit Cloud:** o disco é apagado a cada reinício, então coloque `FTP_HOST`, `FTP_PORT`,
  `FTP_USER`, `FTP_PASSWORD`, `FTP_BASE_DIR` e `ERP_ADMIN_PASSWORD` em **Settings → Secrets**
  (a tela gera o bloco pronto). Se o IP do FTP muda com frequência, use um DNS dinâmico
  (No-IP/DuckDNS) como endereço.

## Instalador para Windows (.exe)

Baixe **`ERP-Obras-Setup.exe`** na release **"ERP Obras para Windows"** do GitHub
(`Releases → instalador-windows`), gerada automaticamente a cada atualização do `main` pelo workflow
`.github/workflows/windows-installer.yml`. O instalador não pede administrador e já inclui:
Python, todas as bibliotecas, **Tesseract com português (OCR de notas fiscais)** e ffmpeg.

- Atalho **ERP Obras** na área de trabalho: abre o sistema no navegador (feche a janela preta para encerrar).
- Dados em `%LOCALAPPDATA%\ERP Obras\data` (preservados ao atualizar/reinstalar).
- No primeiro login do administrador aparece a **escolha do banco de dados**:
  - **Neste computador (disco):** acessível só neste computador; não pelo celular nem remotamente.
  - **No seu FTP:** quem tem o link do sistema publicado acessa de qualquer lugar conforme o nível de
    acesso; no PC, o celular no mesmo Wi-Fi também acessa. PC e site sincronizam pelo FTP e o sistema
    avisa se houver lançamentos simultâneos nos dois.
- Acesso a documentos por usuário: **Gestão de Usuários → Acesso a documentos** (pastas do GED e
  categorias de leis).

Alternativa sem instalador: `iniciar.bat` (requer Python 3.12 instalado) ou `./iniciar.sh` no Linux/macOS.

## Módulos

1. **Controle de acesso (RBAC)** — login na sidebar, 3 perfis, matriz de permissões por checkbox
   para cada usuário, senha provisória com troca obrigatória (PBKDF2-SHA256).
2. **WBS / EAP** — cadastro de entregas e três visualizações alternáveis: Árvore Graphviz,
   Tabela Recuada (estilo MindView) e Kanban (A Fazer / Em Andamento / Concluído). Custo e avanço
   consolidados (roll-up) por nível.
3. **Cronograma, CPM e RDO** — CPM (ida/volta, folga total, data de status, datas reais), Gantt
   interativo com caminho crítico em **vermelho** e contorno da baseline. RDO com clima, mão de obra,
   ocorrências, avanço físico e consumo. **Chuva Forte** (+1 dia nas tarefas externas ativas) ou
   problema em tarefa (+N dias) **recalculam o cronograma em tempo real** — a nova data final aparece
   antes mesmo de salvar. Painel **Baseline x Real** mostra onde se perdeu tempo e dinheiro.
4. **Gestão de NFs** e **Tributos, BDI & Custos** — NF em **PDF** (DANFE com texto ou escaneado),
   foto (upload ou câmera do celular) ou **XML da NF-e**, + foto do produto; leitura do PDF/OCR
   (OpenCV + Tesseract) preenche Valor, Fornecedor, Emissão, CNPJ, nº, ISS, INSS e os itens, que
   cadastram materiais novos automaticamente; abas Incluir NF, Aprovação e Todas as NFs. BDI pela fórmula do Acórdão TCU 2.622/2013 com tributos separados e campo de benefícios fiscais;
   alertas em cotações/NFs de serviço sem destaque de ISS (LC 116/2003) e retenção de 11% de INSS
   (Lei 8.212/91, art. 31). NF aprovada soma ao **CR** e atualiza **IDC, IDP e Curva S (VP x VA x CR)**.
5. **Almoxarifado inteligente** — NF aprovada dá entrada; RDO/consumo diário dá baixa; **alerta
   piscante** quando o saldo não cobre a demanda das próximas tarefas críticas dentro do Lead Time.
6. **Memorial, Time-lapse e Flash Report** — vídeo `.mp4` via OpenCV (Vídeo Geral da Obra e Vídeo
   Filtrado por Etapa, com transcodificação H.264 quando há `ffmpeg`) e **Relatório Executivo (PDF)**
   gerado em memória com ReportLab (~0,5 s).
7. **Proteção à Araucária e Repositório Legal** — checklist por exemplar (raio de proteção =
   máx(copa; 12 × DAP), configurável), integrado ao RDO, disparando **ALERTA VERMELHO de risco de
   embargo**. Repositório de PDFs por categoria (Copel, Sanepar, Bombeiros, Calçadas, ABNT).
8. **Central de Projetos (GED)** — upload de arquivos pesados (PDF, DWG, IFC, ...) nas pastas
   Projetos / Listas de Materiais / Laudos-Licenças, com versionamento automático.
9. **Agenda (vCard)** — importação de `.vcf` (2.1/3.0/4.0, quoted-printable, linhas dobradas) e
   timeline do envolvido: tarefas que gerencia, RDOs que assinou e NFs que emitiu.
10. **Armazenamento duplo** — toda mídia vai **simultaneamente** para AWS S3 (produção) e FTP privado
    (backup em `categoria/AAAA/MM/`), com cache local. Aba **Configurações de Conexão e Backup**
    (somente Admin) reescreve o `.env` **criptografado** (Fernet), tem **Testar Conexão FTP**,
    teste do S3 e reenvio de mídias pendentes.

## Arquitetura

```
app.py                     # entrada: login na sidebar, RBAC e navegação (st.navigation)
erp/
  config.py                # caminhos, perfis, catálogo de módulos
  db.py                    # schema e acesso SQLite (dados textuais)
  security.py              # PBKDF2 (senhas) e Fernet (segredos)
  settings_store.py        # leitura/escrita do .env criptografado
  storage.py               # DualStorage: S3 + FTP em paralelo + cache local
  auth.py                  # usuários, perfis e permissões
  seed.py                  # massa de simulação (determinística, relativa à data de hoje)
  services/project.py      # projeto em branco, novo projeto, demonstração
  services/backup.py       # banco no FTP/S3: envio conferido, versões, restauração
  services/                # regras de negócio, sem Streamlit
    scheduling.py  evm.py  finance.py  ocr.py  inventory.py  rdo.py  wbs.py
    environment.py contacts.py timelapse.py reports.py analytics.py simulation_media.py
  ui/                      # uma página por módulo + componentes (CSS responsivo, gráficos)
tests/                     # pytest + AppTest do Streamlit
sample_data/               # .vcf e imagem de NF de exemplo para testar importação e OCR
```

## Rodando localmente

```bash
pip install -r requirements-dev.txt
# OCR (opcional): sudo apt install tesseract-ocr tesseract-ocr-por ffmpeg
streamlit run app.py
pytest -q
```

Na primeira execução é criado o banco `data/erp_obra.db` em branco (ou a simulação, com `ERP_DEMO=1`).

## Deploy no Streamlit Community Cloud

1. Main file: `app.py`. O `packages.txt` instala `tesseract-ocr`, `tesseract-ocr-por` e `ffmpeg`.
2. Em **Settings → Secrets**, defina `ERP_MASTER_KEY` (veja `.streamlit/secrets.toml.example`).
   Sem ela, uma chave é gerada em `data/.master.key`.
3. Configure S3/FTP pela aba de conexões (logado como `admin`) ou pelos Secrets.

Observações:
- O disco do Community Cloud é efêmero: o SQLite e o `.env` são recriados quando o app reinicia.
  Com o FTP nos Secrets, o banco é restaurado do FTP automaticamente (veja "Banco de dados no FTP").
- Sem Tesseract, o OCR degrada com elegância: basta colar o texto da NF e o mesmo parser preenche
  os campos.
- As integrações com S3 e FTP foram testadas com mocks (sem credenciais reais).

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `ERP_DATA_DIR` | pasta de dados (padrão `./data`) |
| `ERP_DB_PATH` | caminho do SQLite |
| `ERP_ENV_PATH` | caminho do `.env` criptografado |
| `ERP_MASTER_KEY` | chave Fernet para criptografar o `.env` |
| `ERP_ADMIN_PASSWORD` | senha inicial do `admin` num banco novo (evita a senha padrão) |
| `ERP_DEMO` | `1` = carrega a simulação na primeira execução |
| `ERP_STORAGE_MODE` | `ftp` ou `local` (onde fica o banco; sem isso o admin escolhe no 1º login) |
| `ERP_TESSERACT_CMD` | caminho do `tesseract.exe` (o instalador define sozinho) |
