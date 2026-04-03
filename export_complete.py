"""Gera SEO + Music + Teasers e exporta tudo para o Drive."""
import sys
sys.path.insert(0, ".")
from protocols.seo_generator import generate_seo_pack
from protocols.creative_prompts import generate_music_pack, generate_teaser_prompts, generate_thumbnail_prompts
from protocols.google_export import get_drive_service, create_doc, create_sheet, upload_file
from pathlib import Path
from dashboard import save_project

OUTPUT = Path("output")

# Top 15 ideias com dados estruturados
ideas = [
    {"num": 1, "title": "O estagiario que encontrou um bug de $200M na Ethereum", "hook": "Estagiario de 19 anos revisa codigo e descobre falha que poderia destruir a 2a maior crypto do mundo.", "summary": "Historia da vulnerabilidade Parity Wallet", "pillar": "Bugs Tech", "niche": "System Breakers"},
    {"num": 2, "title": "A fraude de $10 bilhoes que enganou Wall Street", "hook": "Vendedor de seguros descobre falha simples nos maiores bancos do mundo. Por 15 anos, ninguem percebeu.", "summary": "Esquema que explorou falta de verificacao entre bancos", "pillar": "Exploits Financeiros", "niche": "System Breakers"},
    {"num": 3, "title": "Adolescente de 15 anos invadiu o Pentagono", "hook": "O Pentagono gasta $10 bilhoes por ano em seguranca. Um garoto de 15 anos entrou usando algo que custou $0.", "summary": "Jonathan James e a invasao da DTRA/NASA", "pillar": "Engenharia Social", "niche": "System Breakers"},
    {"num": 4, "title": "$1.2M em milhas aereas com copos de pudim", "hook": "David Phillips gastou $3.140 em pudim. 12.150 copos. Loucura? Nao. Ele ganhou 1.2 milhao de milhas.", "summary": "O Pudding Guy e a brecha da Healthy Choice", "pillar": "Glitches Legais", "niche": "System Breakers"},
    {"num": 5, "title": "Dinheiro infinito de caixas eletronicos", "hook": "Dan Saunders tentou sacar dinheiro as 2am. O caixa deu. Mas o saldo nao mudou. Em 4 meses: $1.6M.", "summary": "Glitch bancario australiano", "pillar": "Bugs Tech", "niche": "System Breakers"},
    {"num": 6, "title": "Ganhou loteria 4 vezes - PhD Stanford", "hook": "Joan Ginther: 1 em 18 septilhoes. Sorte... ou ela decodificou o algoritmo?", "summary": "A matematica por tras de 4 premios de loteria", "pillar": "Fraudes Geniais", "niche": "System Breakers"},
    {"num": 7, "title": "3 estudantes do MIT quebraram Las Vegas", "hook": "Nerds com cardigans saiam com $100K cada noite de Las Vegas. Tudo legal. $20M em uma decada.", "summary": "MIT Blackjack Team", "pillar": "Fraudes Geniais", "niche": "System Breakers"},
    {"num": 8, "title": "Morador de rua milionario por 3 dias", "hook": "Encontrou cartao no chao. Saldo: $4.2 milhoes. 72 horas de loucura total.", "summary": "Erro bancario que creditou milhoes em conta errada", "pillar": "Bugs Tech", "niche": "System Breakers"},
    {"num": 9, "title": "Flash Crash: $1 trilhao em 5 minutos", "hook": "Trader no quarto da mae causa crash de $1 trilhao na bolsa americana usando spoofing.", "summary": "Navinder Sarao e o Flash Crash de 2010", "pillar": "Bugs Tech", "niche": "System Breakers"},
    {"num": 10, "title": "Mudou o contrato do cartao de credito", "hook": "Russo escaneou contrato do banco, mudou os termos, devolveu. O banco aceitou sem ler.", "summary": "Dmitry Agarkov e o contrato alterado", "pillar": "Glitches Legais", "niche": "System Breakers"},
    {"num": 11, "title": "$15M em roleta usando fisica pura", "hook": "Engenheiro espanhol mediu 10.000 giros de roleta e detectou vies mecanico. Lucrou $15M.", "summary": "Gonzalo Garcia-Pelayo", "pillar": "Fraudes Geniais", "niche": "System Breakers"},
    {"num": 12, "title": "Loteria 14 vezes com matematica", "hook": "Economista romeno calculou: 7.059.052 combinacoes = jackpot garantido. Ganhou 14 vezes.", "summary": "Stefan Mandel e o consorcio de loteria", "pillar": "Fraudes Geniais", "niche": "System Breakers"},
    {"num": 13, "title": "Spotify pagou $1M para silencio", "hook": "Album com 10 faixas de 31s de silencio absoluto. $1M em royalties em 2 meses.", "summary": "Vulfpeck e o album Sleepify", "pillar": "Glitches Legais", "niche": "System Breakers"},
    {"num": 14, "title": "Erro de virgula custou $70M ao governo", "hook": "A diferenca entre 'fruit, plants' e 'fruit plants' custou $70M em impostos.", "summary": "Tariff Act de 1872", "pillar": "Glitches Legais", "niche": "System Breakers"},
    {"num": 15, "title": "Amazon vendendo tudo por $0.01", "hook": "14 horas de bug de repricing automatico. Produtos de $500 por 1 centavo.", "summary": "Bug de algoritmo de precos da Amazon", "pillar": "Bugs Tech", "niche": "System Breakers"},
]

print("=" * 60)
print("  GERANDO SEO + MUSIC + TEASERS + THUMBNAILS")
print("=" * 60)

# 1. SEO Pack
print("\n[1/4] Gerando SEO Pack...")
seo_content = generate_seo_pack(ideas, "System Breakers")
seo_path = OUTPUT / "loaded_dice_seo.md"
seo_path.write_text(seo_content, encoding="utf-8")
print(f"  Salvo: {seo_path}")

# 2. Music Prompts
print("\n[2/4] Gerando Music Prompts...")
music_content = generate_music_pack("System Breakers")
music_path = OUTPUT / "loaded_dice_music.md"
music_path.write_text(music_content, encoding="utf-8")
print(f"  Salvo: {music_path}")

# 3. Teaser Prompts
print("\n[3/4] Gerando Teaser Prompts...")
teaser_content = generate_teaser_prompts(ideas, "System Breakers")
teaser_path = OUTPUT / "loaded_dice_teasers.md"
teaser_path.write_text(teaser_content, encoding="utf-8")
print(f"  Salvo: {teaser_path}")

# 4. Thumbnail Prompts
print("\n[4/4] Gerando Thumbnail Prompts...")
thumb_content = generate_thumbnail_prompts(ideas, "System Breakers")
thumb_path = OUTPUT / "loaded_dice_thumbnails.md"
thumb_path.write_text(thumb_content, encoding="utf-8")
print(f"  Salvo: {thumb_path}")

# Salvar no historico do dashboard
print("\n[+] Salvando no historico...")
project_id = save_project("System Breakers", {
    "sop": str(OUTPUT / "loaded_dice_sop.md"),
    "niches": str(OUTPUT / "loaded_dice_niches.md"),
    "ideas": str(OUTPUT / "loaded_dice_ideas.md"),
    "seo": str(seo_path),
    "music": str(music_path),
    "teasers": str(teaser_path),
    "thumbnails": str(thumb_path),
    "mindmap": str(OUTPUT / "loaded_dice_mindmap.md"),
    "scripts": [
        str(OUTPUT / "loaded_dice_roteiro_1.md"),
        str(OUTPUT / "loaded_dice_roteiro_2.md"),
        str(OUTPUT / "loaded_dice_roteiro_3.md"),
    ],
    "drive_folder": "1BVZfiN7q4NrToiPLllO0yD1aFMplxfRL",
    "channel_original": "Loaded Dice",
    "niche_chosen": "System Breakers",
    "num_ideas": 30,
    "num_scripts": 3,
})
print(f"  Projeto salvo: {project_id}")

# Export para Google Drive
print("\n[+] Exportando novos arquivos para Google Drive...")
folder_id = "1BVZfiN7q4NrToiPLllO0yD1aFMplxfRL"

seo_doc = create_doc("SEO Pack - System Breakers (15 videos)", seo_content, folder_id)
music_doc = create_doc("Music Prompts - Suno Udio MusicGPT", music_content, folder_id)
teaser_doc = create_doc("Teaser Prompts - Shorts Reels TikTok", teaser_content, folder_id)
thumb_doc = create_doc("Thumbnail Prompts - Midjourney DALL-E", thumb_content, folder_id)

# SEO como Sheet tambem
seo_sheet_data = [["#", "Titulo Principal", "Titulo A/B 1", "Titulo A/B 2", "Pilar", "Tags (top 5)"]]
for idea in ideas:
    tags_top = ", ".join([idea["pillar"].lower(), "system breakers", "historia real", "glitch", "exploit"])
    seo_sheet_data.append([
        str(idea["num"]),
        idea["title"],
        f"COMO {idea['title'].replace('O ','').replace('A ','')}",
        f"{idea['title']} (Historia Real)",
        idea["pillar"],
        tags_top,
    ])
create_sheet("SEO Sheet - Titulos e Tags (15 videos)", seo_sheet_data, folder_id)

print(f"\n{'='*60}")
print("  TUDO CONCLUIDO!")
print(f"  Drive: https://drive.google.com/drive/folders/{folder_id}")
print(f"  Dashboard: python dashboard.py (porta 8888)")
print(f"{'='*60}")
