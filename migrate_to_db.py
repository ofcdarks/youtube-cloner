"""Migra dados existentes dos arquivos para SQLite."""
import sys
sys.path.insert(0, ".")
from database import *
from pathlib import Path

OUTPUT = Path("output")

print("Migrando dados para SQLite...")

# 1. Criar projeto
pid = create_project(
    name="System Breakers",
    channel_original="Loaded Dice",
    niche_chosen="System Breakers",
    drive_folder_id="1BVZfiN7q4NrToiPLllO0yD1aFMplxfRL",
)
print(f"Projeto criado: {pid}")

# 2. Salvar nichos
nichos = [
    ("System Breakers", "Falhas, glitches e brechas legais", "$15-30", "Baixa", "#e040fb", True,
     ["Exploits Financeiros", "Bugs Tecnologicos", "Glitches Legais", "Fraudes Geniais", "Engenharia Social"]),
    ("Heist Architects", "Roubos e assaltos engenhosos", "$10-20", "Media", "#448aff", False,
     ["Roubos a Bancos", "Roubos de Arte", "Cyber Heists", "Fugas de Prisao", "Falsificacao"]),
    ("Dark Deals", "Negocios e aquisicoes insanas", "$20-40", "Baixa-Media", "#ff5252", False,
     ["Aquisicoes Hostis", "Contratos Desastrosos", "Apostas Corporativas", "Guerras de Patentes", "Negociacoes"]),
    ("Glitch Hunters", "Bugs e erros na vida real", "$8-15", "Baixa", "#ffd740", False,
     ["Glitches em Maquinas", "Bugs em Apps", "Erros de Preco", "Glitches em Jogos", "Erros Bancarios"]),
    ("Forbidden Strategies", "Estrategias banidas e proibidas", "$12-25", "Baixa", "#00e5ff", False,
     ["Estrategias de Casino", "Trading Proibido", "Persuasao Banida", "Estrategias Militares", "Negociacao Suja"]),
]
for n in nichos:
    save_niche(pid, n[0], n[1], n[2], n[3], n[4], n[5], n[6])
print(f"  {len(nichos)} nichos salvos")

# 3. Salvar ideias
ideas = [
    (1, "O estagiario que encontrou um bug de $200M na Ethereum", "Estagiario de 19 anos revisa codigo e descobre falha que poderia destruir a 2a maior crypto", "Historia da vulnerabilidade Parity Wallet", "Bugs Tech", "ALTA"),
    (2, "A fraude de $10 bilhoes que enganou Wall Street", "Vendedor de seguros descobre falha simples nos maiores bancos do mundo", "Esquema que explorou falta de verificacao entre bancos", "Exploits Financeiros", "ALTA"),
    (3, "Adolescente de 15 anos invadiu o Pentagono", "O Pentagono gasta $10B em seguranca. Um garoto de 15 anos entrou usando algo que custou $0", "Jonathan James e a invasao da DTRA/NASA", "Engenharia Social", "ALTA"),
    (4, "$1.2M em milhas aereas com copos de pudim", "David Phillips gastou $3.140 em pudim. 12.150 copos. Ganhou 1.2M de milhas", "O Pudding Guy e a brecha da Healthy Choice", "Glitches Legais", "ALTA"),
    (5, "Dinheiro infinito de caixas eletronicos", "Dan Saunders tentou sacar as 2am. O caixa deu. Saldo nao mudou. 4 meses: $1.6M", "Glitch bancario australiano", "Bugs Tech", "ALTA"),
    (6, "Ganhou loteria 4 vezes - PhD Stanford", "Joan Ginther: 1 em 18 septilhoes. Sorte ou decodificou o algoritmo?", "A matematica por tras de 4 premios", "Fraudes Geniais", "ALTA"),
    (7, "3 estudantes do MIT quebraram Las Vegas", "Nerds saiam com $100K cada noite. Tudo legal. $20M em uma decada", "MIT Blackjack Team", "Fraudes Geniais", "ALTA"),
    (8, "Morador de rua milionario por 3 dias", "Encontrou cartao no chao. Saldo: $4.2M. 72 horas de loucura", "Erro bancario que creditou milhoes", "Bugs Tech", "ALTA"),
    (9, "Flash Crash: $1 trilhao em 5 minutos", "Trader no quarto da mae causa crash de $1T na bolsa americana", "Navinder Sarao e o Flash Crash de 2010", "Bugs Tech", "ALTA"),
    (10, "Mudou o contrato do cartao de credito", "Russo escaneou contrato, mudou os termos, banco aceitou sem ler", "Dmitry Agarkov e o contrato alterado", "Glitches Legais", "ALTA"),
    (11, "$15M em roleta usando fisica pura", "Engenheiro mediu 10.000 giros e detectou vies mecanico. Lucrou $15M", "Gonzalo Garcia-Pelayo", "Fraudes Geniais", "ALTA"),
    (12, "Loteria 14 vezes com matematica", "Economista romeno: 7.059.052 combinacoes = jackpot garantido", "Stefan Mandel", "Fraudes Geniais", "ALTA"),
    (13, "Spotify pagou $1M para silencio", "Album com 10 faixas de 31s de silencio. $1M em royalties", "Vulfpeck e Sleepify", "Glitches Legais", "MEDIA"),
    (14, "Erro de virgula custou $70M ao governo", "'fruit, plants' vs 'fruit plants' = $70M em impostos", "Tariff Act de 1872", "Glitches Legais", "MEDIA"),
    (15, "Amazon vendendo tudo por $0.01", "14h de repricing bugado. Produtos de $500 por 1 centavo", "Bug de algoritmo de precos", "Bugs Tech", "MEDIA"),
    (16, "Lucrou $2M com seus proprios acidentes", "Seguradoras nao investigam claims < $50K. Ele teve 47 acidentes", "Fraude de seguro em escala industrial", "Exploits Financeiros", "MEDIA"),
    (17, "Comer gratis no McDonalds por 1 ano", "Bug no app de cupons permitia reutilizacao infinita", "Exploracao de bug no sistema de cupons", "Bugs Tech", "MEDIA"),
    (18, "PayPal deu $92 quadrilhoes por erro", "Overflow numerico: saldo maximo de inteiro 64-bit como saldo real", "Erro de overflow no PayPal", "Bugs Tech", "MEDIA"),
    (19, "Viagens infinitas em primeira classe", "AAirpass: $250K por voo ilimitado vitalicio", "O AAirpass da American Airlines", "Glitches Legais", "MEDIA"),
    (20, "Bug que quase destruiu a internet", "376 bytes de buffer overflow = 75.000 servidores offline em 10 min", "SQL Slammer worm 2003", "Bugs Tech", "MEDIA"),
    (21, "Vendeu o mesmo carro 50 vezes", "Nunca tocou um carro. So laptop e impressora. 6 meses de fraude", "Fraude em marketplace de veiculos", "Fraudes Geniais", "MEDIA"),
    (22, "Brecha fiscal: $40M sem impostos", "Professor encontra brecha na pagina 7.432 de lei de 10.000 paginas", "Exploracao de creditos fiscais em cascata", "Exploits Financeiros", "MEDIA"),
    (23, "Glitch no caixa deixou morador de rua milionario", "Ronald Page: cartao no chao, saldo $4.2M, 72h de loucura", "Erro bancario em Detroit", "Bugs Tech", "ALTA"),
    (24, "Exploit nas gorjetas do Uber", "Ex-taxista com gorjetas 10x maiores que qualquer motorista", "Manipulacao de ratings e timing", "Engenharia Social", "BAIXA"),
    (25, "Prefeito eleito com 1 voto", "Bug na maquina de votacao em cidade de 30.000 habitantes", "Falha em votacao eletronica", "Bugs Tech", "BAIXA"),
    (26, "Hackeou sistema de notas da escola", "Servidor de $200K. Senha do admin: password123", "Estudante altera notas de centenas de alunos", "Bugs Tech", "BAIXA"),
    (27, "Netflix gratis para sempre", "Cookie manipulation + virtual cards = trial infinito", "Exploracao do sistema de trials", "Bugs Tech", "BAIXA"),
    (28, "Tinder revelava localizacao exata", "3 pontos de referencia = trilateracao", "Vulnerabilidade de stalking no Tinder", "Bugs Tech", "MEDIA"),
    (29, "Metro gratis por 2 anos via NFC", "Clonagem de cartao via app Android sem criptografia", "Falta de criptografia em bilhetagem", "Bugs Tech", "BAIXA"),
    (30, "Erro de codigo criou dinheiro do nada", "Contador descobre kiting bancario: $9M por 6 anos", "Exploracao de delay interbancario", "Exploits Financeiros", "MEDIA"),
]

idea_ids = {}
for i in ideas:
    iid = save_idea(pid, i[0], i[1], i[2], i[3], i[4], i[5])
    idea_ids[i[0]] = iid
print(f"  {len(ideas)} ideias salvas")

# 4. Salvar roteiros
scripts_data = [
    (1, "Bug de $200M na Ethereum", "9-11 min", "loaded_dice_roteiro_1.md"),
    (2, "$1.2M em milhas com pudim", "8-10 min", "loaded_dice_roteiro_2.md"),
    (3, "MIT vs Las Vegas", "10-12 min", "loaded_dice_roteiro_3.md"),
]
for s in scripts_data:
    content = (OUTPUT / s[3]).read_text(encoding="utf-8")
    save_script(pid, s[1], content, idea_ids.get(s[0]), s[2])
print(f"  {len(scripts_data)} roteiros salvos")

# 5. Salvar arquivos
files_data = [
    ("analise", "SOP - Loaded Dice", "loaded_dice_sop.md", "https://docs.google.com/document/d/1GD9nRPC6gESHsJDHWVBn2W0-AZB0SzrIDtET48U2utU/edit"),
    ("analise", "5 Nichos Derivados", "loaded_dice_niches.md", "https://docs.google.com/document/d/1ynh6eFSQfw2dop4ebzNVYrmZ6y-FC3Q0ozOPROei-Ik/edit"),
    ("analise", "30 Ideias de Videos", "loaded_dice_ideas.md", "https://docs.google.com/document/d/1iRuK5kouIm1ZSWDBySe84RkEUkq_GV51enDdbcOwC9A/edit"),
    ("seo", "SEO Pack Completo", "loaded_dice_seo.md", "https://docs.google.com/document/d/1fkKHVm2QvToVzSG5ZlJ4WLw4pZqk_QO1SW-N8wkKGPs/edit"),
    ("creative", "Music Prompts", "loaded_dice_music.md", "https://docs.google.com/document/d/1xRj01MkxxlTmhTp88doSbEFrCocYrYhLPHT82e1o5Ow/edit"),
    ("creative", "Teaser Prompts", "loaded_dice_teasers.md", "https://docs.google.com/document/d/1EvR4ick1XG7qQ3vCNAxwOi7NZZqrlFxdt5UeVuZKX-U/edit"),
    ("creative", "Thumbnail Prompts", "loaded_dice_thumbnails.md", "https://docs.google.com/document/d/1M_14gosH1GJ8CsKrfLcN3s0qnxMD2iSvSP1oxJoibLE/edit"),
    ("visual", "Mind Map", "loaded_dice_mindmap.md", ""),
]
for f in files_data:
    content = (OUTPUT / f[2]).read_text(encoding="utf-8") if (OUTPUT / f[2]).exists() else ""
    save_file(pid, f[0], f[1], f[2], content, f[3])
print(f"  {len(files_data)} arquivos salvos")

# 6. Log
log_activity(pid, "migration", "Dados migrados de arquivos para SQLite")

stats = get_stats()
print(f"\nMigracao concluida!")
print(f"  Projetos: {stats['projects']}")
print(f"  Ideias: {stats['ideas']}")
print(f"  Roteiros: {stats['scripts']}")
print(f"  Nichos: {stats['niches']}")
print(f"  Arquivos: {stats['files']}")
print(f"  DB: {DB_PATH}")
