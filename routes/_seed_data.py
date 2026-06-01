"""
Static seed data for the ROBOS ENCANTADOS (chibi village) and RELATOS
FAMILIARES projects. Extracted from api_routes.py to keep that module smaller.
Pure data — no logic. Imported by routes/api_routes.py seed endpoints.
"""

_ROBOS_SEED_NICHES = [
    ("Miniature Village Cooking", "Tiny chibi folk making berry jam, baking acorn bread in stone ovens, brewing herbal tea in nutshell cups, preserving honey in glass jars, cooking mushroom soup by the fireplace", "$4-6", "Baja", "#8FB285", True),
    ("Cottagecore Crafts & Artisanry", "Chibi villagers weaving on miniature looms, painting with petal pigments, sewing linen aprons, shaping pottery from river clay, candle-making from beeswax, wood carving on tiny benches", "$4-6", "Baja", "#C9A961", True),
    ("Enchanted Harvest & Foraging", "Tiny folk collecting morning dew drops, picking wild strawberries and blackberries, gathering mushrooms at dawn, fishing in crystal streams, foraging edible flowers", "$3-5", "Baja", "#DAA520", False),
    ("Tiny Village Building & Gardening", "Chibi characters constructing new tree-stump houses, assembling stone bridges over streams, installing waterwheels, hanging firefly lanterns along cobblestone paths, tending flower gardens and herb plots", "$3-6", "Baja", "#B5651D", False),
    ("Magical Forest Discovery", "Tiny villagers discovering crystal caves, finding hidden waterfalls, meeting gentle giant animals (cats, butterflies, ladybugs, deer), exploring moss-covered ruins, following fairy rings at dusk", "$4-7", "Baja", "#6B8E4A", False),
]

# 30 titulos curados seguindo estilo ForestSpirits25 (cottagecore cozy ASMR)
# Variedade: narrativa serie (Tales of X, Chronicles of Y, Diary of Z, Legends of W),
# personagens variados (cottage witch, tiny baker, little elf, chibi potter, etc),
# vilas com nomes proprios (Mossmoor, Leafkins, Thistledown, Willowbend, Acornhill,
# Brackenvale, Hollowbrook), labels de genero sempre no FIM entre [] ou |.
# SEM prefixos genericos tipo "Tiny chibi folk".
_ROBOS_SEED_TITLES = [
    # ─ Miniature Village Cooking (8) ─
    ("Tales of Leafkins: Autumn Berry Preserves in the Acorn Pantry [Cottagecore ASMR]", "Miniature Village Cooking", "ALTA", 40500),
    ("A Cottage Witch Brews Rose Hip Tea at Dawn | Peaceful Forest Sounds & Celtic Harp", "Miniature Village Cooking", "ALTA", 49500),
    ("Diary of a Tiny Baker: First Winter Loaf in Mossmoor Kitchen [Ambient Fantasy Music]", "Miniature Village Cooking", "ALTA", 33100),
    ("Honey Cakes and Golden Mornings in Thistledown Bakery [Relaxing Cottagecore ASMR]", "Miniature Village Cooking", "ALTA", 22200),
    ("Legends of Brackenvale: The Secret Mushroom Soup | Celtic Violin & Forest Ambience", "Miniature Village Cooking", "ALTA", 40500),
    ("Rainy Afternoon Stewing Pumpkin Cider in Hollowbrook Cottage [ASMR Rain & Lofi]", "Miniature Village Cooking", "ALTA", 27100),
    ("A Tiny Tea Master Pours Chamomile in Nutshell Cups [Ambient Fantasy & Forest Sounds]", "Miniature Village Cooking", "MEDIA", 18100),
    ("Fermenting Wild Plums by Candlelight in an Old Cottage Cellar [Cozy Cottagecore ASMR]", "Miniature Village Cooking", "MEDIA", 14800),

    # ─ Cottagecore Crafts & Artisanry (6) ─
    ("Chronicles of Willowbend: The Linen Weaver's Quiet Morning [Cottagecore ASMR]", "Cottagecore Crafts & Artisanry", "ALTA", 40500),
    ("A Chibi Potter Shapes Clay from the Mossmoor River | Peaceful Celtic Music", "Cottagecore Crafts & Artisanry", "MEDIA", 18100),
    ("Sewing a Velvet Cloak by Firelight in a Thistledown Cottage [Cozy Lofi ASMR]", "Cottagecore Crafts & Artisanry", "MEDIA", 14800),
    ("Tales of Acornhill: The Candle Maker's Golden Afternoon [Ambient Fantasy Music]", "Cottagecore Crafts & Artisanry", "ALTA", 22200),
    ("Painting Wildflower Tiles in a Sunlit Miniature Studio | Celtic Harp & Nature Sounds", "Cottagecore Crafts & Artisanry", "MEDIA", 18100),
    ("A Tiny Tailor Embroiders Cherry Blossoms on a Linen Apron [Peaceful ASMR]", "Cottagecore Crafts & Artisanry", "MEDIA", 12100),

    # ─ Enchanted Harvest & Foraging (5) ─
    ("A Little Forest Elf Harvests Morning Dew at Sunrise [Forest ASMR & Celtic Harp]", "Enchanted Harvest & Foraging", "ALTA", 27100),
    ("Gathering Wild Strawberries in the Mossmoor Meadows [Peaceful Cottagecore Music]", "Enchanted Harvest & Foraging", "ALTA", 40500),
    ("Chronicles of Hollowbrook: The Beekeeper's Golden Harvest Day | Celtic ASMR", "Enchanted Harvest & Foraging", "MEDIA", 22200),
    ("Foraging Glowing Mushrooms at Dusk in Brackenvale Forest [Ambient Fantasy]", "Enchanted Harvest & Foraging", "ALTA", 33100),
    ("A Chibi Herbalist Collects Lavender by the Stone Bridge [Relaxing Forest Sounds]", "Enchanted Harvest & Foraging", "MEDIA", 14800),

    # ─ Tiny Village Building & Gardening (6) ─
    ("Tales of Leafkins: The Hidden Library in Hollow Logs [Cottagecore ASMR & Celtic Harp]", "Tiny Village Building & Gardening", "ALTA", 22200),
    ("Building a Spiral Herb Tower in the Enchanted Woods [Peaceful Celtic Music]", "Tiny Village Building & Gardening", "ALTA", 33100),
    ("Lighting Firefly Lanterns Along Acornhill Stone Bridge [Evening Cottagecore ASMR]", "Tiny Village Building & Gardening", "ALTA", 27100),
    ("Legends of Willowbend: The Mushroom Greenhouse [Ambient Fantasy & Celtic Violin]", "Tiny Village Building & Gardening", "MEDIA", 18100),
    ("Diary of a Village Carpenter: A New Treehouse for Spring [Wood Carving ASMR]", "Tiny Village Building & Gardening", "MEDIA", 18100),
    ("First Snow Falls on Brackenvale Cottage Roofs [Peaceful Winter Ambience & Lofi]", "Tiny Village Building & Gardening", "ALTA", 49500),

    # ─ Magical Forest Discovery (5) ─
    ("Finding a Hidden Lake with Golden Lotus Flowers [Calming Ambience & Celtic Harp]", "Magical Forest Discovery", "ALTA", 33100),
    ("A Gentle Giant Ladybug Visits the Mossmoor Garden [Relaxing Forest Sounds]", "Magical Forest Discovery", "ALTA", 74000),
    ("Tales of Thistledown: The Crystal Grove at Golden Hour [Ambient Fantasy Music]", "Magical Forest Discovery", "ALTA", 27100),
    ("A Sleepy Chibi Boy Reads by a Hearth While Rain Falls [Cozy Cottagecore ASMR]", "Magical Forest Discovery", "ALTA", 22200),
    ("Chronicles of Hollowbrook: The Spring Flower Festival | Celtic Harp & Bells", "Magical Forest Discovery", "ALTA", 40500),
]


_RELATOS_SEED_NICHES = [
    ("O Milionário Oculto", "Protagonistas que escondem fortunas bilionárias enquanto são humilhados por parentes gananciosos. Contratos de fachada, heranças secretas, testamentos surpresa.", "$8-14", "Baja", "#FFD700", True),
    ("Guerra Fria Sogra/Cunhada", "Conflitos tóxicos com sogras e cunhadas que tentam destruir casamentos, roubar patrimônio ou expulsar noras/genros da família.", "$6-10", "Baja", "#FF0B0B", True),
    ("Abandono na Velhice", "Idosos abandonados por filhos após uma vida de sacrifício. A revelação de herança secreta ou fortuna oculta inverte o jogo.", "$5-8", "Baja", "#8B0000", False),
    ("Provedor(a) Traído(a)", "Maridos ou esposas que sustentam a família em silêncio e descobrem traição financeira ou emocional do parceiro.", "$5-9", "Media", "#D4AF37", False),
    ("Humilhação Pública Revertida", "Protagonistas humilhados em eventos públicos (casamentos, jantares) que revelam documentos devastadores na frente de todos.", "$7-12", "Baja", "#FFE600", False),
]

_RELATOS_SEED_TITLES = [
    ("Minha sogra me expulsou de casa no dia do meu aniversário. Ela não sabia que o terreno era meu", "Guerra Fria Sogra/Cunhada", "ALTA", 74000),
    ("Eu ganho R$ 50.000 por mês e ninguém sabia disso. Nem a mulher que eu amava", "O Milionário Oculto", "ALTA", 90500),
    ("Minha cunhada falsificou a escritura da casa da minha mãe. O cartório tinha uma surpresa", "Guerra Fria Sogra/Cunhada", "ALTA", 60500),
    ("Uma costureira ganhando 1.700 por mês casou com um bilionário. A família dele tentou destruí-la", "O Milionário Oculto", "ALTA", 110000),
    ("Meus filhos me mandaram para o asilo. Eles não sabiam que eu tinha 4 apartamentos no meu nome", "Abandono na Velhice", "ALTA", 49500),
    ("Meu marido pediu o divórcio na frente da família inteira. Eu sorri e abri a pasta de documentos", "Provedor(a) Traído(a)", "ALTA", 74000),
    ("A sogra mandou a nora embora com uma mala. 3 meses depois descobriu quem pagava todas as contas", "Guerra Fria Sogra/Cunhada", "ALTA", 40500),
    ("Trabalhei 30 anos como zelador. Ninguém sabia que eu era dono do prédio inteiro", "O Milionário Oculto", "ALTA", 60500),
    ("Minha esposa me chamou de fracassado no jantar de Natal. O advogado chegou no dia seguinte", "Provedor(a) Traído(a)", "ALTA", 33100),
    ("Me humilharam no casamento do meu próprio filho. 6 meses depois eu comprei a empresa do genro", "Humilhação Pública Revertida", "ALTA", 49500),
    ("A cunhada roubou a herança da sogra com procuração falsa. O tabelião guardava uma cópia", "Guerra Fria Sogra/Cunhada", "ALTA", 40500),
    ("Fui babá dos netos por 15 anos. Quando fiquei doente me mandaram para um asilo público", "Abandono na Velhice", "ALTA", 33100),
    ("Meu marido escondia uma família paralela. Eu escondia uma fortuna de 3 milhões", "O Milionário Oculto", "ALTA", 74000),
    ("A sogra rasgou meu vestido de noiva na frente dos convidados. O padre parou a cerimônia", "Humilhação Pública Revertida", "ALTA", 49500),
    ("Cuidei da minha sogra por 20 anos. No testamento ela deixou tudo para a cunhada que nunca apareceu", "Abandono na Velhice", "ALTA", 40500),
    ("Meu pai me deserhou. O que ele não sabia é que eu tinha gravado tudo", "O Milionário Oculto", "ALTA", 27100),
    ("A empregada doméstica que eles humilhavam era dona de 12 imóveis na cidade", "O Milionário Oculto", "ALTA", 60500),
    ("Minha cunhada disse que eu era um peso para a família. No dia seguinte mostrei o extrato bancário", "Guerra Fria Sogra/Cunhada", "MEDIA", 22200),
    ("Ele me traiu com a melhor amiga. Eu contratei o melhor advogado da cidade em segredo", "Provedor(a) Traído(a)", "ALTA", 40500),
    ("Fui expulsa da herança do meu próprio pai. O cartório tinha um segundo testamento", "O Milionário Oculto", "ALTA", 33100),
    ("Meus 3 filhos brigaram pela minha herança no hospital. Eu estava acordada ouvindo tudo", "Abandono na Velhice", "ALTA", 49500),
    ("A sogra tentou me internar num asilo. O juiz leu o laudo e mandou prender ela", "Guerra Fria Sogra/Cunhada", "ALTA", 27100),
    ("Meu marido transferiu todos os bens para a amante. O banco tinha um bloqueio judicial", "Provedor(a) Traído(a)", "ALTA", 33100),
    ("Vivi 40 anos num quartinho dos fundos. No dia que saí levei a escritura da mansão", "O Milionário Oculto", "ALTA", 40500),
    ("A nora que eles desprezavam pagou o hospital da sogra quando ninguém mais apareceu", "Guerra Fria Sogra/Cunhada", "MEDIA", 22200),
    ("Minha filha me abandonou num asilo e vendeu minha casa. O corretor era meu amigo", "Abandono na Velhice", "ALTA", 27100),
    ("No jantar de família ela jogou água no meu rosto. Eu coloquei o envelope na mesa e saí em silêncio", "Humilhação Pública Revertida", "ALTA", 33100),
    ("Ele achava que eu mal conseguia pagar o aluguel. Eu tinha R$ 2 milhões na poupança", "O Milionário Oculto", "ALTA", 49500),
    ("A cunhada se apossou da casa da mãe com documento falso. O perito encontrou a fraude em 48 horas", "Guerra Fria Sogra/Cunhada", "ALTA", 27100),
    ("Passei 25 anos sendo chamada de incapaz. No divórcio o juiz leu meu patrimônio e o marido empalideceu", "Provedor(a) Traído(a)", "ALTA", 40500),
]
