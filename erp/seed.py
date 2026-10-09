"""Massa de dados de simulação: edifício residencial de 10 pavimentos em Curitiba/PR.

A simulação é determinística (semente fixa) e relativa à data de hoje, para que a obra
esteja sempre "em andamento" ao abrir o app: ~9 meses executados, estrutura quase
concluída, alvenaria/instalações em curso, com chuvas fortes, atrasos e sobrecustos.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, timedelta

from erp import db
from erp.auth import create_user
from erp.config import ROLE_ADMIN, ROLE_STOCK, ROLE_VIEWER
from erp.services.scheduling import cpm, freeze_baseline
from erp.storage import store_media

ELAPSED_DAYS = 266

# ---------------------------------------------------------------- cadastros base
CONTACTS = [
    # chave, nome, telefone, e-mail, organização, cargo, categoria
    ("eng_resp", "Eng. Marcelo Tavares Kowalski", "41991234567", "marcelo.kowalski@bosqueengenharia.com.br", "Bosque Engenharia", "Engenheiro Responsável Técnico (CREA-PR)", "Equipe"),
    ("eng_plan", "Eng. Carla Mendes Ribeiro", "41992345678", "carla.ribeiro@bosqueengenharia.com.br", "Bosque Engenharia", "Engenheira de Planejamento", "Equipe"),
    ("eng_inst", "Eng. Rafael Nogueira Lima", "41993456789", "rafael.lima@bosqueengenharia.com.br", "Bosque Engenharia", "Engenheiro de Instalações", "Equipe"),
    ("mestre", "José Aparecido dos Santos", "41994567890", "jose.santos@bosqueengenharia.com.br", "Bosque Engenharia", "Mestre de Obras", "Equipe"),
    ("almox", "Luiz Fernando Wisniewski", "41995678901", "almoxarifado@bosqueengenharia.com.br", "Bosque Engenharia", "Almoxarife", "Equipe"),
    ("arq", "Arq. Helena Zanetti Prado", "41996789012", "helena@zanettiarquitetura.com.br", "Zanetti Arquitetura", "Arquiteta Autora do Projeto", "Projetista"),
    ("calc", "Eng. Paulo Henrique Strapasson", "41997890123", "paulo@strapassonestruturas.com.br", "Strapasson Estruturas", "Projetista Estrutural", "Projetista"),
    ("bio", "Bióloga Ana Paula Gnoatto", "41998901234", "ana.gnoatto@verdeconsult.com.br", "Verde Consultoria Ambiental", "Responsável Técnica Ambiental", "Consultor"),
    ("seg", "Téc. Rodrigo Batista Moreira", "41999012345", "rodrigo.sst@bosqueengenharia.com.br", "Bosque Engenharia", "Técnico de Segurança do Trabalho", "Equipe"),
    ("fiscal", "Eng. Beatriz Lacerda Fontes", "41990123456", "beatriz.fontes@agentefinanceiro.com.br", "Agente Financeiro (Plano Empresário)", "Engenheira Fiscal de Medição", "Fiscalização"),
    ("forn_concreto", "Sérgio Bortolini", "4133345566", "vendas@concreteirapinheiral.com.br", "Concreteira Pinheiral Ltda", "Gerente Comercial", "Fornecedor"),
    ("forn_aco", "Marisa Kloster", "4133456677", "comercial@acoiguacu.com.br", "Aço Iguaçu Distribuidora de Ferro Ltda", "Vendedora", "Fornecedor"),
    ("forn_dep", "Valdir Pacheco", "4133567788", "pedidos@depositocuritibano.com.br", "Depósito Curitibano de Materiais Ltda", "Proprietário", "Fornecedor"),
    ("forn_bloco", "Juliana Tesseroli", "4136789900", "vendas@ceramicacampolargo.com.br", "Cerâmica Campo Largo Blocos Ltda", "Representante", "Fornecedor"),
    ("forn_hidro", "Anderson Pires", "4133678899", "orcamento@hidroeletricamateriais.com.br", "Hidroelétrica Comércio de Materiais Ltda", "Vendedor Técnico", "Fornecedor"),
    ("sub_fund", "Eng. Cláudio Ferraz", "4133789900", "obras@fundacoesparana.com.br", "Fundações Paraná Engenharia Ltda", "Diretor Técnico", "Empreiteiro"),
    ("sub_estr", "Admir Gonçalves", "4133890011", "contato@estruturaforte.com.br", "Estrutura Forte Construções Ltda", "Encarregado Geral", "Empreiteiro"),
    ("sub_inst", "Patrícia Hoffmann", "4133901122", "adm@hidroluzinstalacoes.com.br", "Hidroluz Instalações Prediais Ltda", "Gestora de Contratos", "Empreiteiro"),
    ("copel", "Técnico Copel - Atendimento a Projetos", "4133310000", "projetos.atendimento@exemplo-copel.com.br", "Copel Distribuição", "Análise de Projetos de Entrada", "Concessionária"),
    ("sanepar", "Técnico Sanepar - Viabilidade", "4133320000", "viabilidade@exemplo-sanepar.com.br", "Sanepar", "Análise de Viabilidade", "Concessionária"),
]

# fornecedores sem contato na agenda (vinculados depois via importação do .vcf de exemplo)
UNLINKED_SUPPLIERS = {
    "Madeireira Araucária Formas Ltda", "Revestir Porcelanatos Ltda", "Tintas Paranaenses Ltda",
    "Esquadrias Boqueirão Alumínio Ltda", "Alvenaria Pinhais Empreiteira Ltda", "Fachadas Sul Revestimentos Ltda",
    "Elevar Sul Elevadores Ltda", "Canteiro Serviços de Apoio ME",
}

MATERIALS = [
    # código, nome, unidade, custo unitário, lead time (dias), estoque mínimo, fornecedor
    ("M01", "Concreto usinado fck 30 MPa", "m³", 520.0, 3, 0, "Concreteira Pinheiral Ltda"),
    ("M02", "Aço CA-50 (vergalhão)", "kg", 7.80, 15, 2000, "Aço Iguaçu Distribuidora de Ferro Ltda"),
    ("M03", "Cimento CP-II 50 kg", "sc", 38.0, 5, 150, "Depósito Curitibano de Materiais Ltda"),
    ("M04", "Areia média lavada", "m³", 140.0, 4, 20, "Depósito Curitibano de Materiais Ltda"),
    ("M05", "Brita 1", "m³", 150.0, 4, 10, "Depósito Curitibano de Materiais Ltda"),
    ("M06", "Bloco cerâmico 14x19x39", "un", 2.90, 20, 5000, "Cerâmica Campo Largo Blocos Ltda"),
    ("M07", "Argamassa de assentamento", "sc", 22.0, 7, 80, "Depósito Curitibano de Materiais Ltda"),
    ("M08", "Chapa compensado plastificado 18 mm", "ch", 165.0, 12, 0, "Madeireira Araucária Formas Ltda"),
    ("M09", "Tubo PVC esgoto 100 mm", "m", 28.0, 10, 100, "Hidroelétrica Comércio de Materiais Ltda"),
    ("M10", "Tubo PPR água fria/quente 25 mm", "m", 14.0, 10, 200, "Hidroelétrica Comércio de Materiais Ltda"),
    ("M11", "Cabo flexível 2,5 mm²", "m", 3.60, 12, 1000, "Hidroelétrica Comércio de Materiais Ltda"),
    ("M12", "Eletroduto corrugado 25 mm", "m", 2.40, 7, 500, "Hidroelétrica Comércio de Materiais Ltda"),
    ("M13", "Porcelanato 60x60 retificado", "m²", 79.0, 30, 0, "Revestir Porcelanatos Ltda"),
    ("M14", "Argamassa colante AC-III", "sc", 34.0, 7, 0, "Depósito Curitibano de Materiais Ltda"),
    ("M15", "Placa de gesso para forro", "m²", 42.0, 15, 0, "Madeireira Araucária Formas Ltda"),
    ("M16", "Tinta acrílica premium 18 L", "gl", 420.0, 10, 0, "Tintas Paranaenses Ltda"),
    ("M17", "Esquadria de alumínio (janela)", "un", 1450.0, 45, 0, "Esquadrias Boqueirão Alumínio Ltda"),
    ("M18", "Textura acrílica para fachada", "m²", 58.0, 20, 0, "Tintas Paranaenses Ltda"),
    ("M20", "Impermeabilizante asfáltico", "kg", 18.0, 10, 0, "Depósito Curitibano de Materiais Ltda"),
    ("M21", "Kit louças e metais (banheiro)", "kit", 1650.0, 30, 0, "Revestir Porcelanatos Ltda"),
]

WBS = [
    # código, pai, nome, responsável
    ("1", None, "Residencial Bosque das Araucárias", "eng_resp"),
    ("1.1", "1", "Serviços Preliminares", "mestre"),
    ("1.2", "1", "Fundações", "eng_resp"),
    ("1.3", "1", "Estrutura de Concreto Armado", "eng_resp"),
    ("1.3.1", "1.3", "Térreo / Pilotis", "mestre"),
    ("1.3.2", "1.3", "Pavimentos Tipo (1º ao 10º)", "mestre"),
    ("1.3.3", "1.3", "Cobertura e Casa de Máquinas", "mestre"),
    ("1.4", "1", "Vedações", "mestre"),
    ("1.5", "1", "Instalações", "eng_inst"),
    ("1.5.1", "1.5", "Hidrossanitárias", "eng_inst"),
    ("1.5.2", "1.5", "Elétricas, SPDA e Telecom", "eng_inst"),
    ("1.6", "1", "Revestimentos Internos", "eng_plan"),
    ("1.7", "1", "Fachada e Esquadrias", "eng_plan"),
    ("1.8", "1", "Sistemas Prediais (Elevadores e Incêndio)", "eng_inst"),
    ("1.9", "1", "Acabamentos", "eng_plan"),
    ("1.10", "1", "Áreas Externas e Ligações Definitivas", "eng_resp"),
    ("1.11", "1", "Entrega e Legalização (Habite-se)", "eng_resp"),
]

ORD = ["1º", "2º", "3º", "4º", "5º", "6º", "7º", "8º", "9º", "10º"]


def _task_list() -> list[dict]:
    t = []

    def add(code, name, wbs, dur, outdoor, preds, labor, mats=None, resp="mestre"):
        t.append({"code": code, "name": name, "wbs": wbs, "duration": dur, "outdoor": outdoor,
                  "preds": preds, "labor": labor, "materials": mats or {}, "resp": resp})

    add("P01", "Mobilização e canteiro de obras", "1.1", 15, 1, [], 180000, {"M03": 80, "M04": 20, "M05": 10, "M08": 20})
    add("P02", "Locação da obra e gabarito", "1.1", 6, 1, ["P01"], 35000, resp="eng_resp")
    add("P03", "Cercamento de proteção das araucárias", "1.1", 4, 1, ["P01"], 18000, resp="bio")
    add("F01", "Escavação e contenções", "1.2", 14, 1, ["P02", "P03"], 260000, {"M03": 120}, "eng_resp")
    add("F02", "Estacas hélice contínua", "1.2", 20, 1, ["F01"], 380000, {"M01": 420, "M02": 21000}, "eng_resp")
    add("F03", "Blocos de coroamento e vigas baldrame", "1.2", 18, 1, ["F02"], 210000,
        {"M01": 260, "M02": 24000, "M08": 90}, "eng_resp")
    add("F04", "Impermeabilização de baldrames", "1.2", 6, 1, ["F03"], 45000, {"M20": 1800})
    add("E00", "Estrutura do térreo / pilotis", "1.3.1", 22, 1, ["F04"], 260000, {"M01": 150, "M02": 15000, "M08": 120})
    prev = "E00"
    for i in range(10):
        code = f"E{i + 1:02d}"
        mats = {"M01": 110, "M02": 11500}
        if i in (0, 4, 8):
            mats["M08"] = 60  # reposição de fôrmas
        add(code, f"Estrutura do {ORD[i]} pavimento", "1.3.2", 16 if i == 0 else 15, 1, [prev], 210000, mats)
        prev = code
    add("E11", "Estrutura da cobertura e casa de máquinas", "1.3.3", 12, 1, ["E10"], 140000, {"M01": 60, "M02": 6000})
    add("A01", "Alvenaria do 1º ao 3º pavimento", "1.4", 24, 0, ["E04"], 195000, {"M06": 35000, "M07": 230, "M04": 40})
    add("A02", "Alvenaria do 4º ao 6º pavimento", "1.4", 24, 0, ["E07", "A01"], 195000, {"M06": 35000, "M07": 230, "M04": 40})
    add("A03", "Alvenaria do 7º ao 10º pavimento e cobertura", "1.4", 30, 1, ["E11", "A02"], 250000,
        {"M06": 47000, "M07": 300, "M04": 52})
    add("I01", "Instalações hidrossanitárias (prumadas e ramais)", "1.5.1", 60, 0, ["A01"], 420000,
        {"M09": 2600, "M10": 5200}, "eng_inst")
    add("I02", "Instalações elétricas embutidas", "1.5.2", 60, 0, ["A01"], 380000, {"M12": 14000, "M11": 4000}, "eng_inst")
    add("I03", "SPDA, gás e telecom", "1.5.2", 24, 1, ["E11"], 160000, {"M11": 2000}, "eng_inst")
    add("I04", "Enfiação, quadros e prumadas elétricas", "1.5.2", 30, 0, ["I02", "A03"], 240000, {"M11": 26000}, "eng_inst")
    add("R01", "Contrapiso e regularização", "1.6", 35, 0, ["I01"], 260000, {"M03": 1600, "M04": 380}, "eng_plan")
    add("R02", "Reboco interno / gesso liso", "1.6", 45, 0, ["A03", "I02"], 420000,
        {"M03": 1400, "M04": 300, "M07": 500}, "eng_plan")
    add("R03", "Revestimento cerâmico e porcelanato", "1.6", 45, 0, ["R01", "R02"], 360000,
        {"M13": 4800, "M14": 1600}, "eng_plan")
    add("R04", "Forro de gesso", "1.6", 25, 0, ["R02"], 150000, {"M15": 3200}, "eng_plan")
    add("FA1", "Reboco externo (balancim)", "1.7", 45, 1, ["A03"], 380000, {"M03": 1100, "M04": 260}, "eng_plan")
    add("FA2", "Revestimento e textura de fachada", "1.7", 30, 1, ["FA1"], 280000, {"M18": 4200}, "eng_plan")
    add("FA3", "Esquadrias de alumínio e vidros", "1.7", 25, 1, ["FA1"], 220000, {"M17": 160}, "eng_plan")
    add("S01", "Elevadores (instalação e comissionamento)", "1.8", 40, 0, ["E11"], 680000, resp="eng_inst")
    add("S02", "Sistema preventivo de incêndio", "1.8", 25, 0, ["I01"], 210000, {"M10": 800}, "eng_inst")
    add("AC1", "Pintura interna", "1.9", 35, 0, ["R04", "R03"], 300000, {"M16": 420}, "eng_plan")
    add("AC2", "Louças, metais e bancadas", "1.9", 15, 0, ["R03"], 90000, {"M21": 80}, "eng_plan")
    add("AC3", "Portas, ferragens e acabamentos finais", "1.9", 15, 0, ["AC1"], 260000, resp="eng_plan")
    add("EX1", "Calçada acessível (NBR 9050) e muros", "1.10", 12, 1, ["FA2"], 140000,
        {"M03": 300, "M04": 60, "M05": 50}, "eng_resp")
    add("EX2", "Paisagismo e recuperação ambiental (entorno das araucárias)", "1.10", 10, 1, ["EX1"], 90000, resp="bio")
    add("EX3", "Ligações definitivas Copel e Sanepar", "1.10", 12, 1, ["I04", "I01"], 85000, resp="eng_inst")
    add("EN1", "Vistoria do Corpo de Bombeiros (CSCIP)", "1.11", 6, 0, ["S02", "AC1"], 25000, resp="eng_resp")
    add("EN2", "Limpeza final e vistoria de entrega", "1.11", 8, 0, ["AC3", "AC2", "EX2"], 60000, resp="eng_resp")
    add("EN3", "Habite-se e entrega das chaves", "1.11", 6, 0, ["EN1", "EN2", "EX3", "S01"], 30000, resp="eng_resp")
    return t


SERVICE_SUPPLIER = {
    "P": "Canteiro Serviços de Apoio ME", "F": "Fundações Paraná Engenharia Ltda",
    "E": "Estrutura Forte Construções Ltda", "A": "Alvenaria Pinhais Empreiteira Ltda",
    "I": "Hidroluz Instalações Prediais Ltda", "R": "Alvenaria Pinhais Empreiteira Ltda",
    "FA": "Fachadas Sul Revestimentos Ltda", "S": "Elevar Sul Elevadores Ltda",
    "AC": "Canteiro Serviços de Apoio ME", "EX": "Canteiro Serviços de Apoio ME", "EN": "Canteiro Serviços de Apoio ME",
}

LABOR_BY_PREFIX = {
    "P": {"Servente": 6, "Carpinteiro": 2, "Pedreiro": 2},
    "F": {"Operador de máquinas": 3, "Armador": 4, "Servente": 6, "Pedreiro": 2},
    "E": {"Carpinteiro": 8, "Armador": 6, "Pedreiro": 3, "Servente": 6, "Operador de grua": 1},
    "A": {"Pedreiro": 8, "Servente": 6},
    "I": {"Encanador": 4, "Eletricista": 4, "Ajudante": 4},
    "R": {"Pedreiro": 6, "Gesseiro": 4, "Servente": 4},
    "FA": {"Pedreiro": 6, "Servente": 4},
    "S": {"Montador": 3},
    "AC": {"Pintor": 6},
    "EX": {"Pedreiro": 3, "Jardineiro": 2},
    "EN": {"Servente": 4},
}

PROBLEMS = [
    (0.22, 4, "Encontrada camada de rocha na perfuração das estacas; necessário trocar ferramenta de corte."),
    (0.50, 3, "Atraso na entrega do aço CA-50 pela distribuidora (falta de bitola 12,5 mm)."),
    (0.73, 2, "Quebra da bomba de concreto durante a concretagem da laje; concretagem remarcada."),
    (0.90, 2, "Interdição parcial pela fiscalização do trabalho (NR-18: guarda-corpo incompleto na periferia)."),
]

ROUTINE_NOTES = [
    "DDS sobre trabalho em altura e uso de cinto paraquedista.",
    "Recebimento de concreto usinado conferido (slump e corpos de prova moldados).",
    "Visita da fiscalização do agente financeiro para medição mensal.",
    "Inspeção das escoras e fôrmas antes da concretagem.",
    "Limpeza e organização do canteiro (5S).",
    "Conferência de armaduras pelo engenheiro antes da liberação.",
    "Treinamento de integração de novos colaboradores.",
    "Manutenção preventiva da grua realizada.",
    "",
    "",
    "",
]


def _cnpj(rnd: random.Random) -> str:
    base = [rnd.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    for weights in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        s = sum(d * w for d, w in zip(base, weights))
        r = s % 11
        base.append(0 if r < 2 else 11 - r)
    d = "".join(map(str, base))
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _weather(rnd: random.Random, day: date) -> tuple[str, float, float]:
    m = day.month
    summer = m in (12, 1, 2, 3)
    winter = m in (6, 7, 8)
    heavy, light, cloudy = (0.10, 0.22, 0.30) if summer else ((0.04, 0.16, 0.42) if winter else (0.07, 0.20, 0.33))
    x = rnd.random()
    base_temp = {1: 24, 2: 24, 3: 23, 4: 20, 5: 17, 6: 15, 7: 14, 8: 16, 9: 17, 10: 19, 11: 21, 12: 23}[m]
    temp = round(base_temp + rnd.uniform(-4, 4), 1)
    if x < heavy:
        return "Chuva Forte", temp - 3, round(rnd.uniform(35, 85), 1)
    if x < heavy + light:
        return "Chuva Fraca", temp - 1, round(rnd.uniform(2, 15), 1)
    if x < heavy + light + cloudy:
        return "Nublado", temp, 0.0
    return "Ensolarado", temp + 2, 0.0


def _prefix(code: str) -> str:
    return code[:2] if code[:2] in ("FA", "AC", "EX", "EN") else code[0]


def seed_database(today: date | None = None, with_media: bool = True, rng_seed: int = 42) -> dict:
    """Popula o banco (somente se vazio). Retorna um resumo do que foi criado."""
    db.init_db()
    if db.is_seeded():
        return {"skipped": True}
    rnd = random.Random(rng_seed)
    today = today or date.today()
    start = today - timedelta(days=ELAPSED_DAYS)
    start -= timedelta(days=start.weekday())  # segunda-feira

    for key, val in {
        "project_start": start.isoformat(), "daily_indirect_cost": "4800",
        "project_name": "Residencial Bosque das Araucárias", "project_location": "Curitiba/PR",
        "project_description": "Edifício residencial de 10 pavimentos (simulação de demonstração)", "project_area_m2": "6240",
        "project_units": "40", "araucaria_dap_factor": "12", "simulation_today": today.isoformat(),
    }.items():
        db.set_setting(key, val)

    # ---------------------------------------------------------------- contatos e usuários
    contact_ids: dict[str, int] = {}
    org_contact: dict[str, int] = {}
    with db.transaction() as conn:
        for key, name, phone, email, org, title, cat in CONTACTS:
            from erp.services.contacts import format_phone

            cur = conn.execute(
                "INSERT INTO contacts(name, phone, email, organization, title, category, source, created_at) "
                "VALUES (?,?,?,?,?,?, 'simulação', ?)",
                (name, format_phone(phone), email, org, title, cat, f"{start} 08:00:00"),
            )
            contact_ids[key] = int(cur.lastrowid)
            if cat in ("Fornecedor", "Empreiteiro"):
                org_contact[org] = int(cur.lastrowid)

    create_user("admin", "admin123", ROLE_ADMIN, "Eng. Marcelo Tavares Kowalski", contact_id=contact_ids["eng_resp"])
    create_user("almoxarife", "campo123", ROLE_STOCK, "Luiz Fernando Wisniewski", contact_id=contact_ids["almox"])
    create_user("visualizador", "visual123", ROLE_VIEWER, "Diretoria (somente leitura)")
    create_user("fiscal.banco", "Prov@2026", ROLE_VIEWER, "Eng. Beatriz Lacerda Fontes", must_change_password=True,
                permissions=["painel", "cronograma", "rdo", "fiscal"], contact_id=contact_ids["fiscal"])
    create_user("eng.planejamento", "plan2026", ROLE_VIEWER, "Eng. Carla Mendes Ribeiro",
                contact_id=contact_ids["eng_plan"])
    uid = create_user("almox.noturno", "campo456", ROLE_STOCK, "Vigia / Almoxarife Noturno")
    db.execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))

    # ---------------------------------------------------------------- materiais, EAP, tarefas
    mat_ids: dict[str, int] = {}
    mat_info: dict[str, tuple] = {}
    with db.transaction() as conn:
        for code, name, unit, cost, lead, min_stock, supplier in MATERIALS:
            cur = conn.execute(
                "INSERT INTO materials(code, name, unit, unit_cost, lead_time_days, min_stock) VALUES (?,?,?,?,?,?)",
                (code, name, unit, cost, lead, min_stock))
            mat_ids[code] = int(cur.lastrowid)
            mat_info[code] = (name, unit, cost, lead, supplier)

    wbs_ids: dict[str, int] = {}
    with db.transaction() as conn:
        for order, (code, parent, name, resp) in enumerate(WBS):
            cur = conn.execute(
                "INSERT INTO wbs(code, parent_id, name, description, status, responsible_contact_id, sort_order) "
                "VALUES (?,?,?,?,?,?,?)",
                (code, wbs_ids.get(parent) if parent else None, name, f"Entrega {code} - {name}", "A Fazer",
                 contact_ids[resp], order))
            wbs_ids[code] = int(cur.lastrowid)

    tasks = _task_list()
    task_ids: dict[str, int] = {}
    with db.transaction() as conn:
        for t in tasks:
            mat_cost = sum(q * mat_info[m][2] for m, q in t["materials"].items())
            t["material_cost"] = mat_cost
            cur = conn.execute(
                "INSERT INTO tasks(code, name, wbs_id, duration, outdoor, baseline_cost, progress, responsible_contact_id) "
                "VALUES (?,?,?,?,?,?,0,?)",
                (t["code"], t["name"], wbs_ids[t["wbs"]], t["duration"], t["outdoor"],
                 round(mat_cost + t["labor"], 2), contact_ids[t["resp"]]))
            task_ids[t["code"]] = int(cur.lastrowid)
        for t in tasks:
            for p in t["preds"]:
                conn.execute("INSERT INTO task_deps(task_id, predecessor_id, lag) VALUES (?,?,0)",
                             (task_ids[t["code"]], task_ids[p]))
            for m, q in t["materials"].items():
                conn.execute("INSERT INTO task_materials(task_id, material_id, quantity) VALUES (?,?,?)",
                             (task_ids[t["code"]], mat_ids[m], q))
    freeze_baseline()

    # ---------------------------------------------------------------- simulação dia a dia
    by_id = {task_ids[t["code"]]: t for t in tasks}
    preds = {task_ids[t["code"]]: [(task_ids[p], 0) for p in t["preds"]] for t in tasks}
    base_dur = {tid: t["duration"] for tid, t in by_id.items()}
    delay = defaultdict(int)
    progress = defaultdict(float)
    unreported = defaultdict(float)
    impacts: list[tuple] = []          # (date, task_id, days, reason)
    rdos: list[dict] = []
    purchases: list[dict] = []
    purchased: set[tuple[int, str]] = set()
    service_month = defaultdict(float)  # (task_id, yyyymm) -> % executado no mês
    problems = sorted(PROBLEMS)
    total_days = (today - start).days
    photos: list[dict] = []
    late_materials = {"M06", "M07"}  # compras feitas em cima da hora (geram alerta de lead time)

    actual_start: dict[int, int] = {}
    actual_finish: dict[int, int] = {}

    def schedule(dd: int):
        dur = {tid: base_dur[tid] + delay[tid] for tid in by_id}
        min_s, min_f = {}, {}
        fin = {tid: f + 1 for tid, f in actual_finish.items()}
        for tid in by_id:
            p = progress[tid]
            if p <= 0:
                min_s[tid] = dd
            elif p < 100:
                min_f[tid] = dd + math.ceil(dur[tid] * (1 - p / 100))
        return cpm(dur, preds, min_s, min_f, dict(actual_start), fin), dur

    for dd in range(total_days):
        day = start + timedelta(days=dd)
        res, dur = schedule(dd)
        active = [tid for tid, r in res.items() if r.es <= dd < r.ef and progress[tid] < 100]
        weather, temp, rain = _weather(rnd, day)
        working_day = day.weekday() < 6
        notes: list[str] = []
        problem_task = None
        problem_days = 0

        # compras de material: lead time + folga antes do início projetado
        for tid, r in res.items():
            t = by_id[tid]
            for m, q in t["materials"].items():
                if (tid, m) in purchased:
                    continue
                lead = mat_info[m][3]
                trigger = r.es - (2 if m in late_materials else lead + 5)
                if dd >= trigger and working_day:
                    purchased.add((tid, m))
                    purchases.append({"day": day, "task_id": tid, "material": m, "qty": q * 1.04})

        if working_day:
            if weather == "Chuva Forte":
                hit = [tid for tid in active if by_id[tid]["outdoor"]]
                for tid in hit:
                    delay[tid] += 1
                    impacts.append((day, tid, 1, f"Chuva Forte em {day:%d/%m/%Y} - {by_id[tid]['code']}"))
                notes.append("Chuva forte paralisou os serviços externos"
                             + (f" ({', '.join(by_id[t]['code'] for t in hit)}); cronograma recalculado automaticamente." if hit else "."))
            if problems and dd >= problems[0][0] * total_days:
                frac, days, desc = problems.pop(0)
                crit = sorted([tid for tid in active if res[tid].slack <= 0], key=lambda x: by_id[x]["code"])
                if crit:
                    problem_task = crit[0]
                    problem_days = days
                    delay[problem_task] += days
                    impacts.append((day, problem_task, days, desc))
                    notes.append(desc)

        for tid in active:
            t = by_id[tid]
            if t["outdoor"] and weather == "Chuva Forte":
                factor = 0.0
            elif t["outdoor"] and weather == "Chuva Fraca":
                factor = 0.8
            else:
                factor = rnd.uniform(0.9, 1.06)
            inc = min(100.0 / max(base_dur[tid], 1) * factor, 100 - progress[tid])
            actual_start.setdefault(tid, dd)
            progress[tid] = round(progress[tid] + inc, 4)
            if progress[tid] >= 99.5:
                inc += 100 - progress[tid]
                progress[tid] = 100.0
                actual_finish[tid] = dd
            unreported[tid] += inc
            service_month[(tid, f"{day:%Y-%m}-{1 if day.day <= 15 else 2}")] += inc

        if working_day:
            labor: dict[str, int] = defaultdict(int)
            for tid in active:
                for fn, n in LABOR_BY_PREFIX[_prefix(by_id[tid]["code"])].items():
                    labor[fn] += max(1, n + rnd.randint(-1, 1)) if weather != "Chuva Forte" or not by_id[tid]["outdoor"] else 0
            labor["Mestre de obras"] = 1
            labor["Técnico de segurança"] = 1
            routine = rnd.choice(ROUTINE_NOTES)
            if routine:
                notes.append(routine)
            reported = {tid: progress[tid] for tid in list(unreported) if unreported[tid] > 0}
            unreported.clear()
            rdos.append({
                "day": day, "weather": weather, "temp": temp, "rain": rain, "notes": " ".join(notes),
                "problem_task": problem_task, "problem_days": problem_days,
                "signer": contact_ids["eng_resp"] if day.weekday() == 0 else contact_ids["mestre"],
                "labor": {k: v for k, v in labor.items() if v > 0}, "progress": reported,
            })
            if day.weekday() == 4:  # foto semanal (sexta-feira) por etapa ativa
                stages = sorted({by_id[tid]["wbs"].split(".")[0] + "." + by_id[tid]["wbs"].split(".")[1]
                                 for tid in active})[:2]
                for st_code in stages:
                    photos.append({"day": day, "wbs": st_code, "weather": weather,
                                   "state": dict(progress)})

    # ---------------------------------------------------------------- persistência da simulação
    with db.transaction() as conn:
        for tid, p in progress.items():
            conn.execute("UPDATE tasks SET progress = ?, actual_start = ?, actual_finish = ? WHERE id = ?",
                         (round(min(p, 100), 2),
                          (start + timedelta(days=actual_start[tid])).isoformat() if tid in actual_start else None,
                          (start + timedelta(days=actual_finish[tid])).isoformat() if tid in actual_finish else None,
                          tid))
        rdo_by_day: dict[date, int] = {}
        for r in rdos:
            cur = conn.execute(
                "INSERT INTO rdo(date, weather, temperature, rain_mm, occurrences, problem_task_id, problem_days, "
                "signed_by_contact_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (r["day"].isoformat(), r["weather"], r["temp"], r["rain"], r["notes"], r["problem_task"],
                 r["problem_days"], r["signer"], "simulação", f"{r['day']} 17:30:00"))
            rid = int(cur.lastrowid)
            rdo_by_day[r["day"]] = rid
            conn.executemany("INSERT INTO rdo_labor(rdo_id, function, quantity) VALUES (?,?,?)",
                             [(rid, fn, n) for fn, n in r["labor"].items()])
            conn.executemany("INSERT INTO rdo_progress(rdo_id, task_id, progress) VALUES (?,?,?)",
                             [(rid, tid, round(min(p, 100), 2)) for tid, p in r["progress"].items()])
        for day, tid, days, reason in impacts:
            rid = rdo_by_day.get(day)
            conn.execute("INSERT INTO schedule_impacts(rdo_id, task_id, days, reason, created_at) VALUES (?,?,?,?,?)",
                         (rid, tid, days, reason, f"{day} 17:35:00"))

    # consumo diário (baixa pelo RDO) proporcional ao avanço reportado
    prev_prog: dict[int, float] = defaultdict(float)
    consumption: list[tuple] = []
    for r in rdos:
        rid = rdo_by_day[r["day"]]
        for tid, p in r["progress"].items():
            delta = p - prev_prog[tid]
            prev_prog[tid] = p
            for m, q in by_id[tid]["materials"].items():
                qty = round(q * delta / 100.0, 2)
                if qty > 0:
                    consumption.append((mat_ids[m], r["day"].isoformat(), -qty, "SAIDA", "RDO", rid,
                                        f"Consumo {by_id[tid]['code']}", "simulação"))

    # ---------------------------------------------------------------- notas fiscais
    sched_now, _ = schedule(total_days)
    upcoming_crit = {tid for tid, r in sched_now.items()
                     if r.slack <= 0 and progress[tid] <= 0 and r.es - total_days <= 30}
    invoices: list[dict] = []
    supplier_cnpj: dict[str, str] = {}
    counters: dict[str, int] = defaultdict(lambda: rnd.randint(1200, 9800))

    def next_number(supplier: str) -> str:
        counters[supplier] += rnd.randint(1, 9)
        return str(counters[supplier]).zfill(6)

    grouped: dict[tuple, list] = defaultdict(list)
    for p in purchases:
        supplier = mat_info[p["material"]][4]
        grouped[(p["day"], supplier, p["task_id"])].append(p)
    for (day, supplier, tid), items in sorted(grouped.items(), key=lambda x: x[0][0]):
        lines = []
        for p in items:
            m = p["material"]
            price_factor = 1.15 if (m == "M02" and (day - start).days > 90) else rnd.uniform(1.0, 1.09)
            qty = p["qty"]
            if tid in upcoming_crit and m in late_materials:
                qty *= 0.35  # entrega parcial: gera alerta de ruptura no lead time
            lines.append((m, round(qty, 2), round(mat_info[m][2] * price_factor, 2)))
        total = round(sum(q * pr for _, q, pr in lines), 2)
        not_started = progress[tid] <= 0
        status = "Pendente" if (not_started and (today - day).days <= 12) else "Aprovada"
        invoices.append({"supplier": supplier, "day": day, "kind": "Material", "task_id": tid, "lines": lines,
                         "total": total, "iss": 0.0, "inss": 0.0, "status": status})

    overrun = {"F02": 1.28, "F03": 1.12, "E00": 1.10, "E05": 1.18, "E08": 1.15, "A02": 1.14}
    for (tid, month), pct in sorted(service_month.items(), key=lambda x: x[0][1]):
        if pct <= 0.01:
            continue
        t = by_id[tid]
        y, m, half = map(int, month.split("-"))  # medição quinzenal
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        day = min(date(y, m, 15) if half == 1 else nxt - timedelta(days=1), today - timedelta(days=1))
        while day.weekday() == 6:
            day -= timedelta(days=1)
        factor = overrun.get(t["code"], 1.09 if t["code"].startswith("E") else rnd.uniform(1.0, 1.08))
        total = round(t["labor"] * pct / 100.0 * factor, 2)
        recent = (today - day).days <= 10
        iss = round(total * 0.025, 2)
        inss = round(total * 0.55 * 0.11, 2)
        if recent and rnd.random() < 0.5:
            inss = 0.0  # empreiteiro não destacou a retenção: alerta fiscal
        invoices.append({"supplier": SERVICE_SUPPLIER[_prefix(t["code"])], "day": day, "kind": "Serviço",
                         "task_id": tid, "lines": [], "total": total, "iss": iss, "inss": inss,
                         "status": "Pendente" if recent else "Aprovada"})
    # duplicidades rejeitadas
    for inv in [i for i in invoices if i["kind"] == "Serviço" and i["status"] == "Aprovada"][5:7]:
        dup = dict(inv, status="Rejeitada", day=inv["day"] + timedelta(days=2))
        invoices.append(dup)

    invoices.sort(key=lambda i: i["day"])
    stock_entries: list[tuple] = []
    with db.transaction() as conn:
        for inv in invoices:
            supplier = inv["supplier"]
            supplier_cnpj.setdefault(supplier, _cnpj(rnd))
            contact = None if supplier in UNLINKED_SUPPLIERS else org_contact.get(supplier)
            approved_at = f"{inv['day'] + timedelta(days=2)} 10:00:00" if inv["status"] != "Pendente" else None
            benefit = "Desoneração da folha (CPRB) - Lei 12.546/2011" if inv["kind"] == "Serviço" else ""
            cur = conn.execute(
                "INSERT INTO invoices(number, supplier_name, supplier_cnpj, supplier_contact_id, issue_date, total_value, "
                "kind, iss_value, inss_value, other_taxes, tax_benefit, task_id, status, approved_by, approved_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (next_number(supplier), supplier, supplier_cnpj[supplier], contact, inv["day"].isoformat(), inv["total"],
                 inv["kind"], inv["iss"], inv["inss"], round(inv["total"] * 0.0365, 2), benefit, inv["task_id"],
                 inv["status"], "admin" if approved_at else None, approved_at, f"{inv['day']} 09:00:00"))
            inv["id"] = int(cur.lastrowid)
            for m, q, pr in inv["lines"]:
                conn.execute("INSERT INTO invoice_items(invoice_id, material_id, quantity, unit_price) VALUES (?,?,?,?)",
                             (inv["id"], mat_ids[m], q, pr))
                if inv["status"] == "Aprovada":
                    stock_entries.append((mat_ids[m], inv["day"].isoformat(), q, "ENTRADA", "NF", inv["id"],
                                          f"NF {supplier}", "simulação"))
        conn.executemany(
            "INSERT INTO stock_movements(material_id, date, quantity, kind, source, ref_id, notes, created_by) "
            "VALUES (?,?,?,?,?,?,?,?)", stock_entries + consumption)
        # ajuste de inventário (perdas/quebras) mensal
        for m in ("M06",):
            conn.execute(
                "INSERT INTO stock_movements(material_id, date, quantity, kind, source, notes, created_by) "
                "VALUES (?,?,?,?,?,?,?)",
                (mat_ids[m], (today - timedelta(days=20)).isoformat(), -round(rnd.uniform(40, 120)), "AJUSTE",
                 "Inventário", "Quebra/perda apurada no inventário mensal", "almoxarife"))

    # ---------------------------------------------------------------- status da EAP
    _sync_wbs_status()

    # ---------------------------------------------------------------- cotações
    quotes = [
        ("Fachadas Sul Revestimentos Ltda", "Reboco externo com balancim - 10 pavimentos", "Serviço", 395000, 1, 1),
        ("Reboco & Cia Empreiteira", "Reboco externo (proposta alternativa)", "Serviço", 352000, 0, 0),
        ("Elevar Sul Elevadores Ltda", "Fornecimento e montagem de 2 elevadores 8 paradas", "Material + Mão de obra", 690000, 1, 0),
        ("Pintura Total Serviços Ltda", "Pintura interna 40 unidades + áreas comuns", "Serviço", 298000, 0, 1),
        ("Tintas Paranaenses Ltda", "Tinta acrílica premium 18 L (420 gl)", "Material", 172000, 0, 0),
        ("Esquadrias Boqueirão Alumínio Ltda", "Esquadrias de alumínio linha 25 + vidros", "Material + Mão de obra", 238000, 1, 1),
        ("Gesso Forte Instalações", "Forro de gesso acartonado", "Serviço", 149000, 1, 0),
        ("Revestir Porcelanatos Ltda", "Porcelanato 60x60 retificado - 4.800 m²", "Material", 371000, 0, 0),
    ]
    with db.transaction() as conn:
        for sup, desc, kind, val, iss_h, inss_h in quotes:
            conn.execute(
                "INSERT INTO quotes(supplier, description, kind, value, iss_highlighted, inss_highlighted, iss_value, "
                "inss_value, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sup, desc, kind, val, iss_h, inss_h, round(val * 0.025, 2) if iss_h else 0,
                 round(val * 0.5 * 0.11, 2) if inss_h else 0, "Em análise",
                 f"{today - timedelta(days=rnd.randint(3, 40))} 14:00:00"))

    # ---------------------------------------------------------------- araucárias
    trees = [("ARA-01", 62, 6.5, "Divisa norte, junto ao acesso de veículos"),
             ("ARA-02", 48, 5.0, "Recuo frontal, próxima ao estoque de blocos"),
             ("ARA-03", 80, 7.5, "Fundo do lote (APP de preservação)")]
    tree_ids = []
    with db.transaction() as conn:
        for tag, dap, crown, loc in trees:
            cur = conn.execute("INSERT INTO araucaria_trees(tag, dap_cm, crown_radius_m, location, notes) VALUES (?,?,?,?,?)",
                               (tag, dap, crown, loc, "Exemplar adulto preservado conforme licença ambiental."))
            tree_ids.append((int(cur.lastrowid), dap, crown))
    from erp.services.environment import evaluate_inspection, protection_radius

    inspections = []
    for r in rdos:
        if r["day"].weekday() != 0:
            continue
        for tid, dap, crown in tree_ids:
            radius = protection_radius(dap, crown, 12)
            inspections.append((rdo_by_day[r["day"]], tid, r["day"], round(radius + rnd.uniform(0.5, 6), 1),
                                True, False, False, False, False, ""))
    # não conformidade antiga (resolvida) e uma recente (ativa -> alerta de embargo)
    old = [r for r in rdos if (today - r["day"]).days > 150][-1]
    inspections.append((rdo_by_day[old["day"]], tree_ids[0][0], old["day"], 6.0, True, False, True, True, False,
                        "Retroescavadeira cortou raízes superficiais durante escavação; área recomposta."))
    recent = [r for r in rdos if 5 <= (today - r["day"]).days <= 15][0]
    inspections.append((rdo_by_day[recent["day"]], tree_ids[1][0], recent["day"], 4.2, False, False, False, True, True,
                        "Paletes de blocos e entulho depositados dentro do raio de proteção; cerca removida."))
    with db.transaction() as conn:
        tree_map = {t[0]: {"dap_cm": t[1], "crown_radius_m": t[2]} for t in tree_ids}
        for rid, tid, day, dist, fence, crown_d, root_d, soil, stock, note in inspections:
            ok, viol = evaluate_inspection(tree_map[tid], dist, fence, crown_d, root_d, soil, stock)
            conn.execute(
                "INSERT INTO araucaria_inspections(rdo_id, tree_id, date, intervention_distance_m, fence_ok, crown_damage, "
                "root_damage, soil_compaction, material_stockpile, compliant, violations, notes, resolved) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, tid, day.isoformat(), dist, int(fence), int(crown_d), int(root_d), int(soil), int(stock), int(ok),
                 "; ".join(viol), note, 1 if day == old["day"] else 0))

    summary = {
        "start": start, "today": today, "tasks": len(tasks), "rdos": len(rdos), "invoices": len(invoices),
        "impacts": len(impacts), "photos": 0, "users": 6,
    }
    if with_media:
        summary.update(_seed_media(today, start, rdos, rdo_by_day, photos, task_ids, wbs_ids, invoices, mat_info,
                                   mat_ids, supplier_cnpj))
    return summary


def _sync_wbs_status() -> None:
    from erp.services.wbs import sync_status_from_tasks

    sync_status_from_tasks()


def _seed_media(today, start, rdos, rdo_by_day, photos, task_ids, wbs_ids, invoices, mat_info, mat_ids,
                supplier_cnpj) -> dict:
    from datetime import datetime

    from erp.services.reports import build_placeholder_pdf
    from erp.services.simulation_media import render_invoice_image, render_product_photo, render_site_photo

    stage_names = {code: name for code, _, name, _ in WBS}
    code_by_id = {v: k for k, v in task_ids.items()}

    def frac(state, codes):
        return sum(min(state.get(task_ids[c], 0), 100) for c in codes) / 100.0

    rows = []
    for i, ph in enumerate(photos):
        s = ph["state"]
        foundation = frac(s, ["F01", "F02", "F03", "F04"]) / 4
        structure = frac(s, ["E00"] + [f"E{k:02d}" for k in range(1, 12)])
        masonry = frac(s, ["A01"]) * 3 + frac(s, ["A02"]) * 3 + frac(s, ["A03"]) * 5
        facade = frac(s, ["FA1", "FA2"]) / 2
        stage = stage_names[ph["wbs"]]
        img = render_site_photo(ph["day"], foundation, structure, masonry, facade, stage, ph["weather"], seed=i)
        res = store_media(img, f"obra_{ph['day']:%Y%m%d}_{ph['wbs']}.jpg", "fotos-obra", remote=False,
                          when=datetime.combine(ph["day"], datetime.min.time()))
        rows.append((ph["day"].isoformat(), wbs_ids[ph["wbs"]], f"Avanço semanal - {stage}", res.key,
                     rdo_by_day.get(ph["day"])))
    with db.transaction() as conn:
        conn.executemany("INSERT INTO photos(date, wbs_id, caption, media_key, rdo_id) VALUES (?,?,?,?,?)", rows)

    # imagens de NF para as notas mais recentes e pendentes
    recent = [i for i in invoices if i["status"] == "Pendente"] + [i for i in invoices if i["status"] == "Aprovada"][-6:]
    nf_count = 0
    for k, inv in enumerate(recent[:18]):
        number = db.query_one("SELECT number FROM invoices WHERE id = ?", (inv["id"],))["number"]
        items = [(mat_info[m][0], q, mat_info[m][1], pr) for m, q, pr in inv["lines"]] or \
                [(f"Serviço {code_by_id.get(inv['task_id'], '')} - medição", 1, "vb", inv["total"])]
        img = render_invoice_image(number, inv["supplier"], supplier_cnpj[inv["supplier"]], inv["day"], inv["total"],
                                   items, inv["iss"], inv["inss"], inv["kind"])
        nf = store_media(img, f"NF_{number}.png", "notas-fiscais", remote=False)
        prod_key = None
        if inv["lines"]:
            prod = store_media(render_product_photo(mat_info[inv["lines"][0][0]][0], seed=k),
                               f"produto_NF_{number}.jpg", "fotos-produtos", remote=False)
            prod_key = prod.key
        db.execute("UPDATE invoices SET nf_media_key = ?, product_media_key = ? WHERE id = ?",
                   (nf.key, prod_key, inv["id"]))
        nf_count += 1

    # repositório legal (PDFs de referência simulados)
    legal = [
        ("Copel", "NTC 901100 — Fornecimento em tensão secundária de distribuição", "Copel NTC 901100"),
        ("Copel", "Orientações para projeto de entrada de energia de edifícios de uso coletivo", "Copel - Projetos"),
        ("Sanepar", "Normas para ligação de água e esgoto em edificações coletivas", "Sanepar - Ligações"),
        ("Sanepar", "Diretrizes de viabilidade técnica de abastecimento e esgotamento", "Sanepar - Viabilidade"),
        ("Bombeiros", "Código de Segurança Contra Incêndio e Pânico (CSCIP) - CBMPR", "CSCIP/CBMPR"),
        ("Bombeiros", "NPT 011 — Saídas de emergência", "CBMPR NPT 011"),
        ("Calçadas", "Padronização de calçadas - Prefeitura Municipal de Curitiba", "PMC - Calçadas"),
        ("Calçadas", "ABNT NBR 9050:2020 — Acessibilidade a edificações e espaços urbanos", "NBR 9050:2020"),
        ("ABNT", "ABNT NBR 6118:2023 — Projeto de estruturas de concreto", "NBR 6118:2023"),
        ("ABNT", "ABNT NBR 6122:2022 — Projeto e execução de fundações", "NBR 6122:2022"),
        ("ABNT", "ABNT NBR 15575 — Edificações habitacionais: desempenho", "NBR 15575"),
    ]
    for cat, title, ref in legal:
        pdf = build_placeholder_pdf(title, [
            f"Categoria: {cat} · Referência: {ref}",
            "Documento de referência gerado para a SIMULAÇÃO do sistema.",
            "Substitua este arquivo pelo PDF oficial obtido junto ao órgão/concessionária/ABNT.",
        ])
        res = store_media(pdf, f"{ref.replace('/', '-').replace(' ', '_')}.pdf", f"legislacao-{cat}", remote=False)
        db.execute("INSERT INTO legal_docs(category, title, reference, description, media_key, filename, uploaded_at) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (cat, title, ref, "PDF de referência (simulação)", res.key, f"{ref}.pdf", f"{start} 09:00:00"))

    # GED: projetos, listas de materiais, laudos/licenças
    ged = [
        ("Projetos", "Arquitetura", "Projeto arquitetônico executivo - Rev.04", "ARQ-EXE-R04.pdf", "pdf"),
        ("Projetos", "Estrutura", "Formas e armaduras - pavimento tipo - Rev.02", "EST-TIPO-R02.dwg", "dwg"),
        ("Projetos", "BIM", "Modelo federado BIM (arquitetura + estrutura)", "BOSQUE-FEDERADO.ifc", "ifc"),
        ("Projetos", "Hidrossanitário", "Projeto hidrossanitário - Rev.03", "HID-R03.pdf", "pdf"),
        ("Projetos", "Elétrico", "Projeto elétrico e SPDA - Rev.02", "ELE-SPDA-R02.dwg", "dwg"),
        ("Projetos", "Incêndio", "Projeto preventivo de incêndio (PSCIP) aprovado", "PSCIP-APROVADO.pdf", "pdf"),
        ("Listas de Materiais", "Quantitativos", "Lista de materiais por tarefa (quantitativo)", "quantitativos.csv", "csv"),
        ("Listas de Materiais", "Estrutura", "Tabela de aço - pavimentos tipo", "tabela_aco.csv", "csv"),
        ("Laudos/Licenças", "Legal", "Alvará de construção", "ALVARA-CONSTRUCAO.pdf", "pdf"),
        ("Laudos/Licenças", "Ambiental", "Licença ambiental e termo de preservação das araucárias", "LICENCA-AMBIENTAL.pdf", "pdf"),
        ("Laudos/Licenças", "Geotecnia", "Laudo de sondagem SPT (8 furos)", "LAUDO-SPT.pdf", "pdf"),
        ("Laudos/Licenças", "Responsabilidade técnica", "ART de execução - CREA-PR", "ART-EXECUCAO.pdf", "pdf"),
        ("Laudos/Licenças", "Vizinhança", "Laudo cautelar de vizinhança", "LAUDO-VIZINHANCA.pdf", "pdf"),
    ]
    mats = db.query("SELECT t.code, t.name, m.name AS material, m.unit, tm.quantity FROM task_materials tm "
                    "JOIN tasks t ON t.id = tm.task_id JOIN materials m ON m.id = tm.material_id ORDER BY t.code")
    for folder, disc, title, fname, ext in ged:
        if ext == "pdf":
            data = build_placeholder_pdf(title, [f"Disciplina: {disc}", "Arquivo de simulação do GED."])
        elif ext == "csv":
            lines = ["tarefa;descricao;material;unidade;quantidade"] + [
                f"{r['code']};{r['name']};{r['material']};{r['unit']};{r['quantity']:.2f}" for r in mats]
            data = "\n".join(lines).encode("utf-8")
        elif ext == "ifc":
            data = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
                    f"FILE_NAME('{fname}','{today}T09:00:00',('ERP Obras'),('Simulação'),'','','');\n"
                    "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n#1=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,"
                    "'Residencial Bosque das Araucarias',$,$,$,$,$,$);\nENDSEC;\nEND-ISO-10303-21;\n").encode()
        else:
            data = b"AC1032" + b"\x00" * 512  # cabeçalho DWG (placeholder de simulação)
        res = store_media(data, fname, f"ged-{folder}", remote=False)
        db.execute("INSERT INTO ged_files(folder, discipline, title, filename, extension, size_bytes, version, media_key, "
                   "uploaded_by, uploaded_at, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (folder, disc, title, fname, ext, len(data), 1, res.key, "admin", f"{start + timedelta(days=3)} 10:00:00",
                    "Arquivo de simulação"))
    return {"photos": len(rows), "nf_images": nf_count, "legal_docs": len(legal), "ged_files": len(ged)}
