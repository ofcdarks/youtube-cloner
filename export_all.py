"""Exporta tudo do Loaded Dice para Google Drive."""
import sys
sys.path.insert(0, ".")
from protocols.google_export import create_folder, create_doc, create_sheet

OUTPUT = "output"

print("=" * 60)
print("  EXPORTANDO TUDO PARA GOOGLE DRIVE")
print("=" * 60)

# 1. Criar pasta
print("\n[1/6] Criando pasta...")
folder_id = create_folder("YT Cloner - System Breakers (Loaded Dice)")

# 2. SOP
print("\n[2/6] SOP...")
with open(f"{OUTPUT}/loaded_dice_sop.md", encoding="utf-8") as f:
    create_doc("SOP - Loaded Dice (Analise Estrutural)", f.read(), folder_id)

# 3. Nichos
print("\n[3/6] Nichos...")
with open(f"{OUTPUT}/loaded_dice_niches.md", encoding="utf-8") as f:
    create_doc("5 Nichos Derivados - Niche Bending", f.read(), folder_id)

# 4. Ideias como Doc e Sheet
print("\n[4/6] Ideias de Videos...")
with open(f"{OUTPUT}/loaded_dice_ideas.md", encoding="utf-8") as f:
    create_doc("30 Ideias de Videos - System Breakers", f.read(), folder_id)

# Sheet com as ideias
ideas_data = [
    ["#", "Titulo", "Hook (30s)", "Nicho", "Prioridade"],
    ["1", "O estagiario que encontrou um bug de $200M na Ethereum", "Estagiario de 19 anos revisa codigo, encontra falha que poderia destruir a 2a maior crypto", "Bugs Tech", "ALTA"],
    ["2", "A fraude de $10 bilhoes que enganou Wall Street", "Vendedor de seguros descobre falha simples nos maiores bancos do mundo", "Exploits Financeiros", "ALTA"],
    ["3", "Adolescente de 15 anos invadiu o Pentagono", "Garoto de Miami entra no sistema que custou $10B usando algo que custou $0", "Engenharia Social", "ALTA"],
    ["4", "$1.2M em milhas aereas com copos de pudim", "Engenheiro gasta $3.140 em pudim e ganha 1.2M de milhas", "Glitches Legais", "ALTA"],
    ["5", "Sacar dinheiro infinito de caixas eletronicos", "Dan Saunders descobre glitch as 2am - saldo nao muda apos saque", "Bugs Tech", "ALTA"],
    ["6", "Ganhou $4M na loteria 4 vezes (PhD Stanford)", "Joan Ginther: 1 em 18 septilhoes de chance. Ou ela decodificou o algoritmo?", "Glitches Legais", "ALTA"],
    ["7", "3 estudantes do MIT quebraram Las Vegas", "Nerds com cardigans saiam com $100K cada noite. Completamente legal.", "Fraudes Geniais", "ALTA"],
    ["8", "Vendeu o mesmo carro 50 vezes", "Nunca tocou um carro. Nunca pisou em concessionaria. So laptop e impressora.", "Fraudes Geniais", "MEDIA"],
    ["9", "Brecha fiscal: $40M sem pagar impostos", "Professor encontra brecha na pagina 7.432 de lei tributaria de 10.000 paginas", "Exploits Financeiros", "MEDIA"],
    ["10", "Morador de rua milionario por 3 dias", "Encontrou cartao no chao. Saldo: $4.2 milhoes. 72 horas de loucura.", "Bugs Tech", "ALTA"],
    ["11", "Spotify pagou $1M para musica de silencio", "Album com 10 faixas de 31s de silencio absoluto. $1M em royalties.", "Glitches Legais", "MEDIA"],
    ["12", "Erro de virgula custou $70M ao governo", "Diferenca entre 'fruit, plants' e 'fruit plants' = $70M em impostos", "Glitches Legais", "MEDIA"],
    ["13", "Criar dinheiro do nada no sistema bancario", "Contador descobre kiting bancario: $9M que nao existiam por 6 anos", "Exploits Financeiros", "MEDIA"],
    ["14", "Flash Crash: $1 trilhao em 5 minutos", "Trader no quarto da mae causa crash global usando spoofing algoritmico", "Bugs Tech", "ALTA"],
    ["15", "Comer gratis no McDonalds por 1 ano", "Bug no app de cupons permitia reutilizacao infinita", "Bugs Tech", "MEDIA"],
    ["16", "Lucrou $2M com seus proprios acidentes", "Seguradoras nao investigam claims < $50K. Ele teve 47 'acidentes'", "Exploits Financeiros", "MEDIA"],
    ["17", "Amazon vendendo produtos de $500 por $0.01", "14 horas de repricing automatico bugado = maior liquidacao acidental", "Bugs Tech", "MEDIA"],
    ["18", "Exploit nas gorjetas do Uber", "Ex-taxista com gorjetas 10x maiores que qualquer motorista", "Engenharia Social", "BAIXA"],
    ["19", "Prefeito eleito com 1 voto", "Bug na maquina de votacao em cidade de 30.000 habitantes", "Bugs Tech", "BAIXA"],
    ["20", "Mudou o contrato do cartao de credito", "Russo escaneou contrato, mudou os termos, banco aceitou sem ler", "Glitches Legais", "ALTA"],
    ["21", "Viagens infinitas em primeira classe", "AAirpass: $250K por voo ilimitado vitalicio. Custou $1M/ano ao airline", "Glitches Legais", "MEDIA"],
    ["22", "Hackeou o sistema de notas da escola", "Servidor de $200K. Senha do admin: password123", "Bugs Tech", "BAIXA"],
    ["23", "PayPal deu $92 quadrilhoes por erro", "Overflow numerico: saldo maximo de inteiro 64-bit como saldo real", "Bugs Tech", "MEDIA"],
    ["24", "$15M em roleta usando fisica", "Engenheiro mediu 10.000 giros e detectou vies mecanico na roleta", "Fraudes Geniais", "ALTA"],
    ["25", "Bug que quase destruiu a internet em 2003", "376 bytes de buffer overflow = 75.000 servidores offline em 10 min", "Bugs Tech", "MEDIA"],
    ["26", "Ganhou loteria 14 vezes com matematica", "Economista romeno calculou que precisava de 7.059.052 combinacoes", "Fraudes Geniais", "ALTA"],
    ["27", "Avioes desapareceram do radar por 2h", "Bug de GPS existia ha 20 anos sem ser encontrado", "Bugs Tech", "BAIXA"],
    ["28", "Netflix gratis para sempre", "Cookie manipulation + virtual cards = trial infinito", "Bugs Tech", "BAIXA"],
    ["29", "Tinder revelava localizacao exata", "3 pontos de referencia = trilateracao. Stalking vulnerability.", "Bugs Tech", "MEDIA"],
    ["30", "Metro gratis por 2 anos via NFC", "Clonagem de cartao de transporte via app Android sem criptografia", "Bugs Tech", "BAIXA"],
]
create_sheet("Planilha de Ideias - System Breakers (30 videos)", ideas_data, folder_id)

# 5. Roteiros
print("\n[5/6] Roteiros...")
for i in range(1, 4):
    with open(f"{OUTPUT}/loaded_dice_roteiro_{i}.md", encoding="utf-8") as f:
        create_doc(f"Roteiro {i} - System Breakers", f.read(), folder_id)

# 6. Mind Map
print("\n[6/6] Mind Map...")
with open(f"{OUTPUT}/loaded_dice_mindmap.md", encoding="utf-8") as f:
    create_doc("MIND MAP - System Breakers (Loaded Dice)", f.read(), folder_id)

# Mind map como sheet tambem
mindmap_data = [
    ["Categoria", "Subcategoria", "Detalhe", "Status"],
    ["Canal Original", "Loaded Dice", "Poker/Gambling - Low Poly 3D", "Analisado"],
    ["Canal Original", "Metricas", "13 videos = 85M views", "Analisado"],
    ["Canal Original", "Hook Playbook", "9 frameworks de ganchos", "Extraido"],
    ["Canal Original", "Storytelling", "Pattern Interrupts + Open Loops + Specific Spikes", "Extraido"],
    ["Canal Original", "Script Blueprint", "Hook > Contexto > 3 Atos > Climax > CTA", "Extraido"],
    ["", "", "", ""],
    ["Novo Canal", "System Breakers", "Falhas, Glitches, Brechas Legais", "Escolhido"],
    ["Novo Canal", "RPM Estimado", "$15-30 (Muito Alto)", ""],
    ["Novo Canal", "Competicao", "Baixa", ""],
    ["Novo Canal", "Pilar 1", "Exploits Financeiros", ""],
    ["Novo Canal", "Pilar 2", "Bugs Tecnologicos", ""],
    ["Novo Canal", "Pilar 3", "Glitches Legais", ""],
    ["Novo Canal", "Pilar 4", "Fraudes Geniais", ""],
    ["Novo Canal", "Pilar 5", "Engenharia Social", ""],
    ["", "", "", ""],
    ["Producao", "Roteirista", "IA (Claude) + SOP", "Configurado"],
    ["Producao", "Animacao", "Freelancers Upwork $80-300/video", "A contratar"],
    ["Producao", "Frequencia", "2-3 videos/semana", "Meta"],
    ["Producao", "Receita Estimada", "$5K-15K/mes (apos 10 videos)", "Projecao"],
    ["", "", "", ""],
    ["Nichos Alternativos", "Heist Architects", "Roubos engenhosos - RPM Alto", "Disponivel"],
    ["Nichos Alternativos", "Dark Deals", "Negocios insanos - RPM Muito Alto", "Disponivel"],
    ["Nichos Alternativos", "Glitch Hunters", "Bugs na vida real - RPM Medio", "Disponivel"],
    ["Nichos Alternativos", "Forbidden Strategies", "Estrategias banidas - RPM Alto", "Disponivel"],
    ["", "", "", ""],
    ["Pipeline", "Protocol Clerk", "Analisa concorrencia -> SOP", "OK"],
    ["Pipeline", "Niche Bending", "Gera nichos derivados", "OK"],
    ["Pipeline", "Script Stealing", "Gera ideias + roteiros", "OK"],
    ["Pipeline", "Google Export", "Drive/Docs/Sheets automatico", "OK"],
]
create_sheet("MIND MAP - Visao Geral do Projeto", mindmap_data, folder_id)

print("\n" + "=" * 60)
print("  TUDO EXPORTADO!")
print(f"  Pasta: https://drive.google.com/drive/folders/{folder_id}")
print("=" * 60)
