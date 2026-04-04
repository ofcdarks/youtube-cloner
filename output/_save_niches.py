"""
Salva 5 sub-nichos para o projeto Ghibli Cozy Life no banco de dados.
Nicho principal: Ghibli-style Faceless ASMR + Animation / Slow Living
"""
import sys
sys.path.insert(0, ".")
from database import save_niche

PROJECT_ID = "20260403_235301_ghibli_cozy_life"

nichos = [
    (
        "Raindrop Hearth",
        "Videos imersivos de dias chuvosos e nevados em cabanas acolhedoras, "
        "com sons de chuva, lareiras crepitantes e refeicoes quentes preparadas em silencio. "
        "O pilar mais forte do nicho Ghibli — alto engajamento e watch time.",
        "$2.00-$4.50",
        "Media",
        "#5C6BC0",
        True,
        [
            "Chuva em Cabanas e Casas na Floresta",
            "Noites de Neve com Lareira e Cobertores",
            "Tempestades Acolhedoras com Cha e Leitura",
            "Manhãs Nubladas com Cafe e Janelas Embaçadas",
            "Sons de Chuva + Culinaria Silenciosa",
        ],
    ),
    (
        "Wilderness Kitchen",
        "Culinaria ASMR faceless em cenarios inusitados — casas na arvore, barcos flutuantes, "
        "vulcoes, cabanas de bambu. Combina construcao artesanal com preparo de refeicoes elaboradas. "
        "Forte apelo visual e alta retenção por curiosidade.",
        "$1.50-$3.50",
        "Media",
        "#66BB6A",
        False,
        [
            "Culinaria em Casas na Arvore",
            "Cozinhando em Jardins Flutuantes",
            "Refeicoes Rustiscas ao Ar Livre",
            "Construcao Artesanal + Comida",
            "Cenarios Fantasticos de Sobrevivencia",
        ],
    ),
    (
        "Grandma's Seasons",
        "Nostalgia familiar centrada na figura dos avos — colheitas sazonais, receitas de infancia, "
        "e momentos afetivos entre geracoes. Gatilho emocional fortissimo que gera comentarios "
        "e compartilhamentos organicos.",
        "$1.50-$3.00",
        "Baixa",
        "#FF8A65",
        False,
        [
            "Receitas da Avo com Ingredientes do Quintal",
            "Colheita Sazonal com a Familia",
            "Memorias de Infancia no Campo",
            "Preparo de Conservas e Fermentados Tradicionais",
            "Tardes com Avos — Cha, Historias e Silencio",
        ],
    ),
    (
        "Solitude Rituals",
        "Rotinas silenciosas de quem mora sozinho — manhãs lentas, limpeza da casa, culinaria para um, "
        "noites com livros e velas. Conecta com o publico jovem urbano que busca paz e auto-cuidado.",
        "$1.80-$3.50",
        "Baixa-Media",
        "#AB47BC",
        False,
        [
            "Uma Semana Morando Sozinho",
            "Rotina Matinal Silenciosa",
            "Cozinhando para Um — Refeicoes Reconfortantes",
            "Limpeza e Organizacao Meditativa",
            "Noites Solitarias com Velas e Livros",
        ],
    ),
    (
        "Harvest Whisper",
        "Colheitas sazonais, jardinagem e forageamento na natureza — frutas silvestres, cogumelos, "
        "ervas e vegetais do campo. Estetica Ghibli pura com ciclos da natureza. "
        "Nicho menor mas com audiencia muito fiel e baixa competicao.",
        "$1.20-$2.50",
        "Baixa",
        "#FDD835",
        False,
        [
            "Forageamento de Cogumelos e Ervas",
            "Colheita de Frutas por Estacao",
            "Plantio e Jardinagem no Campo",
            "Mercados Rurais e Ingredientes Frescos",
            "Secagem, Conserva e Preparo Pos-Colheita",
        ],
    ),
]

for n in nichos:
    save_niche(PROJECT_ID, n[0], n[1], n[2], n[3], n[4], n[5], n[6])

print(f"✓ {len(nichos)} sub-nichos salvos para '{PROJECT_ID}'")
print()
for n in nichos:
    marker = " ← CHOSEN" if n[5] else ""
    print(f"  [{n[4]}] {n[0]} | RPM: {n[2]} | Comp: {n[3]}{marker}")
