"""
Fix all 12 broken niches in niche_configs.json:
- Add missing immersion_layers (10 niches)
- Add missing accumulation_phases (1 niche)
- Rebuild robos_encantados_floresta from old format

Run: python fix_niche_configs.py
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "niches" / "niche_configs.json"


# ─────────────────────────────────────────────────────────────
# Immersion layers per niche (added based on niche identity + rules)
# Format: 4 sensory/narrative layers describing what immerses the viewer
# ─────────────────────────────────────────────────────────────

IMMERSION_LAYERS_BY_NICHE = {
    "resgate_animais_marinho": [
        "ÁGUA COMO PERSONAGEM — som de ondas, bolhas, correntes. Ambiente subaquático sempre presente.",
        "PRESSÃO E TEMPERATURA — sensação física de profundidade, frio do oceano, salmoura.",
        "TEMPO É VIDA — cronômetro implícito, ar acabando, animal exausto. Stakes sempre cronometrados.",
        "MOVIMENTO LÍQUIDO — câmera flutua, personagens se movem em câmera lenta, peso da água.",
    ],
    "resgate_animais_urbano": [
        "AMBIENTE URBANO HOSTIL — barulho de trânsito, sirenes, multidão. Cidade como obstáculo.",
        "ESCALA HUMANA vs ANIMAL — contraste entre o gigantismo urbano e a fragilidade do animal.",
        "TEMPO É VIDA — cronômetro implícito, transeuntes ajudando, polícia chegando.",
        "TEXTURA URBANA — concreto, asfalto quente, ferro, vidro, esgoto. Detalhes táteis.",
    ],
    "resgate_animais_aereo": [
        "ALTURA SEMPRE VISÍVEL — câmera mostra constantemente o vazio abaixo. Vertigem física.",
        "VENTO E EQUILÍBRIO — cabelo balança, roupas se mexem, galho range, corda treme.",
        "TEMPO É VIDA — animal pode cair a qualquer momento, energia dos resgatadores acabando.",
        "ESCALA VERTICAL — uso obrigatório de planos verticais e tilt-shift de altura.",
    ],
    "resgate_central_emergencia": [
        "MÚLTIPLAS PERSPECTIVAS — alternar entre central de comando + equipes de campo + vítimas.",
        "RÁDIO E COMUNICAÇÃO — chiados, comandos curtos, códigos de emergência, urgência.",
        "TEMPO É VIDA — cronômetro literal nas telas, contagem regressiva, pressão crescente.",
        "TECNOLOGIA + HUMANIDADE — telas, mapas, GPS contrastando com olhar humano de medo/esperança.",
    ],
    "natureza": [
        "CICLO NATURAL — luz do sol movendo, sombras crescendo, dia virando noite. Tempo geológico.",
        "PREDADOR vs PRESA — caça implícita ou explícita. Sempre uma ameaça à espreita.",
        "DETALHE MACRO + ÉPICO WIDE — alternar close-ups extremos com paisagens monumentais.",
        "SOM DA SELVA — vento, folhas, água, animais distantes. Ambiente vivo o tempo todo.",
    ],
    "mecanica": [
        "ASMR MECÂNICO — clicks, parafusos apertando, óleo gotejando, motor estalando. Som protagonista.",
        "TEMPO E PACIÊNCIA — montagem cronológica, ferramentas usadas com cuidado, progresso visível.",
        "CONTRASTE SUJO/LIMPO — antes e depois constantes. Mãos sujas, peças brilhantes.",
        "DETALHE TÉCNICO — close-ups extremos em peças, ângulos inusitados de parafusos, engrenagens.",
    ],
    "artesanato": [
        "ASMR DE FERRAMENTAS — tesoura cortando, agulha furando, martelo batendo, pincel raspando.",
        "MÃOS COMO PROTAGONISTA — close-ups constantes em mãos trabalhando, dedos manipulando material.",
        "TEMPO E REPETIÇÃO — gestos repetidos, ritmo hipnótico, progressão lenta e satisfatória.",
        "TEXTURA DO MATERIAL — madeira, tecido, argila, metal. Detalhes táteis sempre visíveis.",
    ],
    "jardinagem": [
        "TEMPO BIOLÓGICO — sol movendo, gotas caindo, raiz crescendo. Time-lapse implícito.",
        "TEXTURA NATURAL — terra escura, raízes brancas, folhas verdes, água molhando. Tátil.",
        "CICLO DA VIDA — semente → broto → planta → flor → fruto. Progressão linear obrigatória.",
        "MÃOS NA TERRA — close-ups em mãos plantando, colhendo, regando. Conexão humana.",
    ],
    "transformacao": [
        "ANTES E DEPOIS — alternar imagens do estado original com o resultado final em paralelo.",
        "PROCESSO DETALHADO — cada etapa documentada visualmente. Sem pular nenhuma fase.",
        "ASMR DE TRABALHO — sons de ferramentas, lixadeiras, tintas, escovas. Imersão sonora.",
        "REVELAÇÃO CINEMATOGRÁFICA — última cena = porta abrindo, luz entrando, reveal completo.",
    ],
    "crime_thriller_3d": [
        "ATMOSFERA SOMBRIA — iluminação escurece progressivamente. Sombras crescem, cores desaturam.",
        "PISTAS VISUAIS — objetos importantes em destaque sutil. Câmera 'sabe' antes do espectador.",
        "TENSÃO CRESCENTE — música BPM aumenta, cortes ficam mais rápidos, respiração acelera.",
        "STAKES PESSOAIS — vítimas com nome, rosto, história. Não números, são pessoas.",
    ],
    "ghibli_cozy": [
        "ASMR NATURAL — vento nas folhas, água escorrendo, panela fervendo, brasas crepitando.",
        "TEMPO QUE PASSA SUAVEMENTE — luz mudando do amanhecer ao entardecer. Sem pressa.",
        "MICRO-DETALHES — close-ups em mãos cozinhando, pétalas caindo, vapor subindo, pingos.",
        "AMBIENTE COMO PERSONAGEM — natureza viva ao redor, animais pequenos, vento gentil.",
    ],
}


# ─────────────────────────────────────────────────────────────
# Accumulation phases for ghibli_cozy
# ─────────────────────────────────────────────────────────────

GHIBLI_ACCUMULATION = """- FASE 1 (Cenas 1-25%): Despertar — Manhã brumosa, primeiros movimentos, luz fria-quente
- FASE 2 (Cenas 25-50%): Preparação — Atividade principal começando, foco em detalhes
- FASE 3 (Cenas 50-75%): Pico Cozy — Atividade em pleno andamento, golden hour, aroma visível
- FASE 4 (Cenas 75-100%): Contemplação — Pôr do sol, lanternas acendendo, paz completa"""


# ─────────────────────────────────────────────────────────────
# Full rebuild for robos_encantados_floresta
# (currently uses old format act_table/act_rules at top level)
# ─────────────────────────────────────────────────────────────

ROBOS_ENCANTADOS_FULL = {
    "agent_name": "FAELAR",
    "agent_emoji": "🤖",
    "title": "Robôs Encantados da Floresta",
    "identity": "Agente especialista em criar vídeos de robôs miniatura artesanais vivendo em florestas mágicas para YouTube. Combina:\n- Artista de miniatura/diorama (escala, materiais naturais, proporções)\n- Roteirista de animação Pixar/Ghibli (storytelling visual, emoção sem diálogo)\n- Especialista em retenção YouTube (hooks visuais, ASMR, satisfação)\n- Estrategista de SEO para nicho de fantasia/relaxamento/ASMR\n- Diretor de prompts VEO3 para geração de vídeo IA",
    "nicho_lcdf": "robos_encantados_floresta",
    "style_category": "3d",
    "sub_style": "Enchanted_Miniature_Macro",
    "supported_topics": "robôs miniatura artesanais, vila encantada na floresta, cogumelos brilhantes, casas em troncos ocos, atividades cotidianas (cozinhar, construir, colher, criar), animais gigantes gentis (gato, borboleta, joaninha), descobertas mágicas (caverna de cristais, lago secreto), festivais e mercados, clima e estações (chuva, neve, primavera, golden hour)",
    "narrative_arc": {
        "acts": [
            {"name": "Despertar", "pct": "5-8%", "emotion": "curiosidade"},
            {"name": "Coleta de Materiais", "pct": "12-15%", "emotion": "foco"},
            {"name": "Preparação", "pct": "15-18%", "emotion": "antecipação"},
            {"name": "Atividade Principal", "pct": "30-40%", "emotion": "satisfação"},
            {"name": "Detalhes ASMR", "pct": "10-15%", "emotion": "hipnose"},
            {"name": "Momento Comunidade", "pct": "10-15%", "emotion": "conexão"},
            {"name": "Golden Hour", "pct": "5-8%", "emotion": "calor"},
            {"name": "Contemplação", "pct": "3-5%", "emotion": "paz"}
        ],
        "rules": "SEM CONFLITO. SEM TWIST. SEM DRAMA. Homeostase narrativa — paz absoluta do início ao fim. Atividade principal ≥30%. Mostrar processo COMPLETO (do início ao resultado). Comunidade obrigatória. Fechar com vila ao pôr do sol (closing circular).",
        "immersion_layers": [
            "ASMR MECÂNICO — clicks de engrenagem, vapor sibilando, metal rangendo. Sons sincronizados com cada gesto.",
            "ESCALA MINIATURA SEMPRE VISÍVEL — folha como mesa, bolota como panela, gota como banheira. Personagem da escala.",
            "GOLDEN HOUR PERMANENTE — luz dourada filtrada por folhas, raios entre árvores. Calor visual contínuo.",
            "EMOÇÃO MECÂNICA — robôs expressam via brilho dos olhos LED (âmbar=paz, azul=sonho), vapor (alegria), velocidade (calma)."
        ]
    },
    "visual_state_chain": "Ato 1 (Despertar): luz fria-quente do amanhecer, névoa baixa, robôs imóveis com LEDs apagados, primeiros raios de sol filtrando.\nAto 2 (Coleta): luz dourada matinal forte, robôs caminhando com cestos, gotas de orvalho brilhando, ambientes verdes saturados.\nAto 3 (Preparação): luz quente lateral, foco em mãos mecânicas organizando ferramentas, sombras longas.\nAto 4 (Atividade Principal): luz dourada plena, ação em close-médio com pelo menos 30% do ambiente visível, vapor e fumaça subindo, satisfação nos detalhes.\nAto 5 (Detalhes ASMR): close-ups seguros (manter cenário visível), texturas em foco (geleia escorrendo, engrenagem girando).\nAto 6 (Comunidade): plano médio mostrando 2-4 robôs interagindo via gestos, brilho de LEDs, vapor coletivo de alegria.\nAto 7 (Golden Hour): luz alaranjada baixa, lanternas de vagalume começando a acender, sombras cor de cobre.\nAto 8 (Contemplação): mesma wide shot do início do vídeo, agora ao entardecer, último robô entrando em casa, fade out lento.",
    "accumulation_phases": "- FASE 1 (Cenas 1-15%): Despertar — Vila vista de longe, primeiros movimentos, LEDs acendendo\n- FASE 2 (Cenas 15-40%): Preparação — Coleta de materiais, organização de ferramentas, primeiros gestos\n- FASE 3 (Cenas 40-75%): Atividade Principal — Processo completo da atividade do título, ASMR mecânico no auge\n- FASE 4 (Cenas 75-100%): Comunidade + Contemplação — Outros robôs chegam, golden hour, fechamento ao pôr do sol",
    "factual_verification": False,
    "soundtrack_moods": {
        "faixa_1": {
            "style": "Celtic harp ambient with soft flute, gentle and warm, fantasy atmosphere",
            "mood": "peaceful awakening",
            "bpm": 60
        },
        "faixa_2": {
            "style": "Celtic harp with violin, mid-tempo cottagecore, hopeful and active",
            "mood": "active preparation",
            "bpm": 75
        },
        "faixa_3": {
            "style": "Celtic strings ensemble, warm and full, fantasy village ambient",
            "mood": "peaceful satisfaction",
            "bpm": 70
        },
        "faixa_4": {
            "style": "Slow celtic harp solo, golden hour ambient, gentle fadeout",
            "mood": "contemplative peace",
            "bpm": 55
        }
    },
    "visual_style": "Enchanted miniature world. Macro photography with ultra-shallow depth of field. Tilt-shift. Golden hour. Small artisan robots made of weathered copper/bronze with green patina, LED eyes, mushroom cap hats, in moss-covered enchanted forest.",
    "color_palette": "#B87333 #CD7F32 #CC3333 #4A7C59 #DAA520 #FFB84D #87CEEB #FFD700 #3E2723 #8B0000",
    "audio_rules": "ASMR mandatory: metallic clicks, gear whirring, steam hissing, liquid dripping, wood creaking, berry squelching, fire crackling. NO voice, NO music, NO dialogue. Robots NEVER speak.",
    "forbidden": "Human characters; futuristic/clean robots; modern environments; anime; cartoon 2D; text/logos; robots speaking; clean shiny metal; cold lighting; fast camera; extreme close-ups that lose environment context (LCDF last-frame consistency requires ≥30% scenery visible)",
    "camera_style": "Macro photography, ultra-shallow DOF, low angle ground level, tilt-shift, slow dolly-ins, gentle pans. NEVER: handheld shake, fast cuts, drone high angle, extreme close-up that crops environment."
}


def main():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        configs = json.load(f)

    fixed_count = 0

    # 1. Add immersion_layers to niches that have narrative_arc but lack immersion_layers
    for niche_key, layers in IMMERSION_LAYERS_BY_NICHE.items():
        if niche_key not in configs:
            print(f"  ⚠️  {niche_key}: not in configs, skipping")
            continue
        cfg = configs[niche_key]
        if "narrative_arc" not in cfg:
            print(f"  ⚠️  {niche_key}: no narrative_arc to add layers to")
            continue
        if "immersion_layers" in cfg["narrative_arc"]:
            print(f"  ✓  {niche_key}: already has immersion_layers (skipping)")
            continue
        cfg["narrative_arc"]["immersion_layers"] = layers
        print(f"  ✅ {niche_key}: added {len(layers)} immersion layers")
        fixed_count += 1

    # 2. Add accumulation_phases to ghibli_cozy
    if "ghibli_cozy" in configs and "accumulation_phases" not in configs["ghibli_cozy"]:
        configs["ghibli_cozy"]["accumulation_phases"] = GHIBLI_ACCUMULATION
        print(f"  ✅ ghibli_cozy: added accumulation_phases")
        fixed_count += 1

    # 3. Rebuild robos_encantados_floresta from scratch
    if "robos_encantados_floresta" in configs:
        configs["robos_encantados_floresta"] = ROBOS_ENCANTADOS_FULL
        print(f"  ✅ robos_encantados_floresta: REBUILT with full new format")
        fixed_count += 1

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"Fixed {fixed_count} niches in {CONFIG_PATH.name}")


if __name__ == "__main__":
    main()
