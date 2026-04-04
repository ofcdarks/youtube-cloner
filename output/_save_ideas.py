"""
30 Video Ideas — Ghibli Cozy Life
Canal: Ghibli Cozy Life
Nicho: Ghibli-Style Faceless ASMR + Animation / Slow Living
Data: 2026-04-03
"""

import sys

sys.path.insert(0, ".")

from database import save_idea

PROJECT_ID = "20260403_235301_ghibli_cozy_life"

IDEAS = [
    # =========================================================================
    # PILAR 1: Clima e Aconchego (35%) — 10 ideas
    # =========================================================================
    {
        "num": 1,
        "title": "A Rainy Night in a Cozy Cabin: Making Hot Ramen & Listening to the Storm | Ghibli-Style ASMR",
        "hook": (
            "[Sound of heavy rain hitting a wooden roof, fireplace crackling softly] "
            "\"Here... careful, it's still very hot.\" [Sound of a cup being placed on the table, steam rising] "
            "\"I'm so glad we made it before the storm. Listen... it sounds like the whole sky is falling out there. "
            "But in here... in here it's so warm. You know what goes perfectly with a night like this? "
            "I brought those fresh noodles from the village market. I'll make that ramen grandma always made when it rained hard. "
            "You remember the smell? Stay here, wrap yourself in the blanket. It'll be ready before you know it.\""
        ),
        "summary": "Video porta de entrada do canal. Cabana na chuva + lamen quente ativa instinto primitivo de abrigo e conforto. Indexa nas buscas de 'rain ASMR', 'cozy cabin', 'Ghibli style' e 'ramen ASMR' simultaneamente.",
        "pillar": "Clima e Aconchego",
        "priority": "ALTA",
    },
    {
        "num": 2,
        "title": "Snowy Morning in a Tiny Treehouse: Making Hot Chocolate & Cinnamon Pancakes | Ghibli-Style ASMR",
        "hook": (
            "[Sound of cold gentle wind, branches creaking under snow weight, lone bird singing] "
            "\"You're awake... come look at this.\" [Sound of blanket being pushed aside, steps on creaking wood] "
            "\"The snow covered everything overnight. Look out the window... the trees look like they're made of sugar. "
            "Stay up here, I'll make something special. I brought that good cocoa powder and fresh cinnamon. "
            "While the pancakes brown on the stove, we'll watch the world turn white down below. "
            "No need to go down. No need to go anywhere. Today, the whole world fits inside this little treehouse.\""
        ),
        "summary": "Neve + casa na arvore combina escapismo Ghibli com curiosidade de 'como seria viver assim?'. Casa na arvore adiciona fantasia e infancia. Cenario diferenciado de cabanas comuns.",
        "pillar": "Clima e Aconchego",
        "priority": "ALTA",
    },
    {
        "num": 3,
        "title": "A Thunderstorm Night in an Old Countryside House: Frying Tempura & Warm Miso Soup | Ghibli-Style ASMR",
        "hook": (
            "[Sound of distant thunder, heavy rain, wooden window rattling gently] "
            "\"Oh... did you hear that?\" [Sound of closer thunder, thick drops on tile roof] "
            "\"Looks like this storm will last the whole night. Good. I love when it rains like this — "
            "strong enough to make you feel protected, but not scared. The old house creaks a little, "
            "but she's survived storms far worse than this one. You know what I'm going to make? Tempura. "
            "The sound of batter hitting hot oil mixed with the sound of rain... it's the best symphony there is. "
            "Stay close. It'll warm you up.\""
        ),
        "summary": "Trovoes adicionam camada dramatica ao ASMR sem quebrar o conforto. Tempura e miso sao receitas iconicas do universo Ghibli. 'Thunderstorm ASMR' tem altissimo volume de busca.",
        "pillar": "Clima e Aconchego",
        "priority": "ALTA",
    },
    {
        "num": 4,
        "title": "The First Snow of Winter: Cozy Night by the Fireplace, Baking Apple Pie & Warm Cider | Ghibli Cozy Life",
        "hook": (
            "[Sound of deep silence broken by snowflakes touching the window, fireplace crackling] "
            "\"Look out the window... it's starting.\" [Sound of curtain being gently pulled, sigh of wonder] "
            "\"The first snow. It always feels magical, no matter how many times you've seen it. "
            "When I was little, my mother would light the fireplace and say: 'First day of snow deserves apple pie.' "
            "I never forgot. Today I have the most beautiful apples from the market, cinnamon, fresh butter... "
            "and this fireplace that creaks just like hers. Stay here with me. "
            "While the snow covers the world outside, we'll fill this house with the coziest smell there is.\""
        ),
        "summary": "Cenario universalmente reconfortante: primeira neve + lareira + torta de maca. Combina Clima/Aconchego com toques de nostalgia familiar. Forte apelo sazonal outono/inverno.",
        "pillar": "Clima e Aconchego",
        "priority": "ALTA",
    },
    {
        "num": 5,
        "title": "Cozy Rainy Afternoon in a Floating Houseboat: Grilling Fish & Watching the River Flow | Ghibli-Style ASMR",
        "hook": (
            "[Sound of water gently hitting a wooden hull, light rain, boat creaking softly] "
            "\"Listen... it's just the rain and the river.\" [Sound of fishing net being pulled in, a fish splashing] "
            "\"Some days I wake up and can't believe I live here. A little floating house in the middle of the river, "
            "surrounded by green. When it rains like this, the boat sways so slowly it feels like a cradle. "
            "Today I caught two beautiful fish early this morning. I'll grill them right here on the deck "
            "with herbs that grow in the little pot by the window. The smell of fresh fish on the fire "
            "mixed with the sound of rain on the river... there's no greater peace than this.\""
        ),
        "summary": "Cenario unico de casa flutuante que combina Clima/Aconchego com toque inusitado. Inspirado no sucesso de 'Peaceful Life on a Floating Garden' (764K views). Evita fadiga de cenarios repetidos.",
        "pillar": "Clima e Aconchego",
        "priority": "MEDIA",
    },
    {
        "num": 6,
        "title": "Foggy Morning in a Mountain Cottage: Brewing Fresh Coffee & Baking Sourdough Bread | Ghibli-Style ASMR",
        "hook": (
            "[Sound of morning birds muffled by fog, kettle beginning to whistle, wooden floor creaking] "
            "\"The fog swallowed the whole valley overnight.\" [Sound of window latch clicking open, cool breeze entering] "
            "\"You can barely see past the garden. It's like we're floating inside a cloud. "
            "I love mornings like this — when the world disappears and all that's left is this kitchen, "
            "the smell of coffee, and the sound of bread crust cracking as it cools. "
            "I started the sourdough before dawn. It should be ready by now. "
            "Come, let's have breakfast while the fog keeps the world at bay.\""
        ),
        "summary": "Neblina como variacao de clima cria atmosfera misteriosamente aconchegante. Cafe + pao sao universais. Cottage na montanha oferece cenario novo e escapista.",
        "pillar": "Clima e Aconchego",
        "priority": "MEDIA",
    },
    {
        "num": 7,
        "title": "A Gentle Spring Rain: Opening the Windows & Making Strawberry Shortcake | Ghibli Cozy Life",
        "hook": (
            "[Sound of soft spring rain, birds singing between drops, window being unlatched] "
            "\"Finally... the rain came.\" [Sound of deep breath, petrichor almost palpable] "
            "\"Can you smell that? The garden has been waiting for this for weeks. "
            "The strawberries are going to be so happy. I picked the last ripe ones this morning — "
            "they're so red they almost glow. I'm going to make that shortcake my aunt used to bring "
            "every spring when the rain started. Whipped cream, sponge cake, and berries "
            "that taste like the sun stored all its warmth inside them. "
            "Let's leave the windows open. The rain sounds better when it's this close.\""
        ),
        "summary": "Chuva de primavera traz variedade sazonal ao pilar. Morango + bolo sao visualmente atrativos para thumbnails. Diferencia do foco inverno/neve com tom mais leve e luminoso.",
        "pillar": "Clima e Aconchego",
        "priority": "MEDIA",
    },
    {
        "num": 8,
        "title": "Sleeping in a Lighthouse During a Storm: Warming Clam Chowder & Candlelight | Ghibli-Style ASMR",
        "hook": (
            "[Sound of powerful waves crashing, wind howling, lighthouse beam rotating with a low hum] "
            "\"The storm came faster than they said.\" [Sound of heavy metal door closing, instant muffling of wind] "
            "\"But that's okay. This old lighthouse has stood against a thousand storms. "
            "Look — someone left candles, a blanket, and there's a small stove in the corner. "
            "I have clams, potatoes, and cream in my bag. While the waves rage against the rocks below "
            "and the light keeps spinning above us, we'll have the warmest bowl of chowder "
            "you've ever tasted. Just us, the candles, and the sea.\""
        ),
        "summary": "Farol durante tempestade e cenario unico e cinematografico. Contraste entre perigo externo e conforto interno gera CTR excepcional. Clam chowder e comida reconfortante perfeita.",
        "pillar": "Clima e Aconchego",
        "priority": "ALTA",
    },
    {
        "num": 9,
        "title": "Midnight Snowfall at a Hot Spring Inn: Warm Sake & Steaming Dumplings | Ghibli-Style ASMR",
        "hook": (
            "[Sound of snow falling silently, hot water bubbling in outdoor onsen, distant wind chimes] "
            "\"Look up... the snowflakes look like stars falling.\" [Sound of sliding wooden door, warm steam escaping] "
            "\"There's something about a hot spring on a snowy night that makes everything feel eternal. "
            "The water is so warm your bones forget they were ever cold. "
            "I brought fresh dumplings from the kitchen downstairs and a small flask of warm sake. "
            "Let's sit by the window where we can watch the snow pile up on the bamboo "
            "while the steam wraps around us like a second blanket. No rush. Nowhere to be.\""
        ),
        "summary": "Onsen japones na neve combina estetica Ghibli pura com ASMR de agua quente. Sake e dumplings sao iconicos. Cenario altamente visual para thumbnail com vapor e neve.",
        "pillar": "Clima e Aconchego",
        "priority": "ALTA",
    },
    {
        "num": 10,
        "title": "Watching the Northern Lights from a Glass Igloo: Hot Berry Tea & Cinnamon Rolls | Ghibli-Style ASMR",
        "hook": (
            "[Sound of absolute arctic silence, faint crackling of aurora, heating system humming softly] "
            "\"Don't move... look above us.\" [Sound of blanket rustling, a quiet gasp] "
            "\"The sky is dancing. Green, purple, blue — like the universe is painting just for us tonight. "
            "This glass igloo was the best idea we ever had. The cold can't reach us in here, "
            "but the beauty can. I'm going to heat up some berry tea — the kind with wild blueberries "
            "and a drop of honey — and those cinnamon rolls I baked this afternoon are still warm. "
            "Let's just lie here and watch the sky tell its story.\""
        ),
        "summary": "Iglu de vidro com aurora boreal e cenario de fantasia maxima. Extremamente visual e unico no nicho. Cha de frutas vermelhas e cinnamon rolls completam o aconchego. Video projetado para viralizar.",
        "pillar": "Clima e Aconchego",
        "priority": "ALTA",
    },
    # =========================================================================
    # PILAR 2: Culinaria e Vida Extrema (25%) — 8 ideas
    # =========================================================================
    {
        "num": 11,
        "title": "Living Inside a Cave During a Blizzard: Stone Oven Bread & Warm Stew | Ghibli-Style ASMR",
        "hook": (
            "[Sound of howling wind, snow hitting rocky walls, subtle echo] "
            "\"We made it... just in time.\" [Sound of footsteps on stone, backpack hitting the ground] "
            "\"The blizzard is too strong to keep going. But look at this place... "
            "someone's been here before. Stacked stones, a perfect spot for a fire. "
            "Let's set up camp. I brought flour and fresh vegetables. "
            "While the snow covers everything outside, I'll bake bread on hot stones "
            "and make a stew that will warm your soul. Stay close to the fire. We're safe here.\""
        ),
        "summary": "Contraste entre perigo externo (nevasca, caverna) e conforto interno (pao, ensopado) gera CTR altissimo. Cenario extremo diferenciador do nicho. 'Survival cooking ASMR' tem alta curiosidade.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "ALTA",
    },
    {
        "num": 12,
        "title": "Surviving a Winter Storm in an Abandoned Train Car: Homemade Stew & Candlelight | Ghibli-Style ASMR",
        "hook": (
            "[Sound of cutting wind, metal vibrating, footsteps in deep snow] "
            "\"There... do you see it? That train car.\" [Sound of heavy metal door being pried open, wind dying as they enter] "
            "\"I couldn't feel my fingers anymore. But look at this... there are still seats, "
            "a little table in the corner. It's almost like someone left this place ready for us. "
            "I'll light these candles. I brought enough firewood for a small fire "
            "and ingredients for a stew. While the storm rages outside "
            "and this train goes nowhere... let's turn this abandoned car "
            "into the coziest dinner you've ever had.\""
        ),
        "summary": "Vagao de trem abandonado na neve e cenario inspirado nos maiores sucessos do Ghibli-Style ASMR. Sobrevivencia confortavel e ponto mais diferenciador do nicho.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "ALTA",
    },
    {
        "num": 13,
        "title": "Cooking on a Volcanic Cliff: Roasting Corn & Making Lava-Heated Soup | Ghibli-Style ASMR",
        "hook": (
            "[Sound of deep earth rumbling, wind at altitude, distant hissing of volcanic vents] "
            "\"Feel that? The ground is warm.\" [Sound of boots on rocky terrain, bag being opened] "
            "\"Most people run away from volcanoes. But this spot right here — "
            "where the earth breathes warm air through the cracks — it's nature's own kitchen. "
            "I brought fresh corn and vegetables. I'm going to roast them right here "
            "on stones heated by the earth itself. And this soup? "
            "The water from that spring over there is already warm. "
            "Nature is doing half the cooking for us. Let's eat where the planet is alive.\""
        ),
        "summary": "Vulcao como cenario extremo inspirado no 'Living Inside a Volcano' do Ghibli-Style ASMR. Culinaria com calor natural da terra e conceito unico e altamente clicavel.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "ALTA",
    },
    {
        "num": 14,
        "title": "Building a Bamboo Kitchen from Scratch: First Meal in Our Forest Home | Ghibli-Style ASMR",
        "hook": (
            "[Sound of machete cutting bamboo, birds calling, river flowing nearby] "
            "\"This one is perfect. Strong, thick, and straight.\" [Sound of bamboo cracking and falling] "
            "\"Every great home starts with a kitchen. And every kitchen starts with a table. "
            "Today we're building ours from what the forest gives us — bamboo for the frame, "
            "big leaves for the roof, flat stones for the cooking surface. "
            "By sunset, this clearing will have a real kitchen. And the first meal? "
            "Rice cooked in a bamboo tube over an open fire, with grilled fish from the river. "
            "Let's build something beautiful from nothing.\""
        ),
        "summary": "Construcao + primeira refeicao combina satisfacao de 'building from scratch' com culinaria. Inspirado no sucesso de 'Building a Bamboo House' (442K views). Alto tempo de retencao.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "ALTA",
    },
    {
        "num": 15,
        "title": "Cooking Inside an Abandoned Plane on a Cliff: Noodle Soup & Mountain Wind | Ghibli-Style ASMR",
        "hook": (
            "[Sound of mountain wind whistling through metal, creaking fuselage, distant eagle cry] "
            "\"It's been here for decades... and it's still standing.\" [Sound of climbing into the cockpit, settling in] "
            "\"An old cargo plane, resting on a cliff like it chose this spot to retire. "
            "The windows are cracked but the cabin is dry. The seats make a decent bed "
            "and this little space between the cargo hold and the cockpit? Perfect for cooking. "
            "I have noodles, broth, green onions, and a small camp stove. "
            "While the wind shakes the wings outside, we'll have the highest restaurant in the world.\""
        ),
        "summary": "Aviao abandonado no penhasco e cenario icônico do Ghibli-Style ASMR. Extremamente cinematografico e diferenciado. Noodle soup e comida universal e reconfortante.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "ALTA",
    },
    {
        "num": 16,
        "title": "Overnight in a Desert Oasis: Clay Oven Flatbread & Mint Tea Under the Stars | Ghibli-Style ASMR",
        "hook": (
            "[Sound of gentle desert wind, water trickling from a spring, sand shifting softly] "
            "\"After three days of sand... water.\" [Sound of cupped hands scooping water, a relieved sigh] "
            "\"This oasis is like something from a dream. Palm trees, a freshwater spring, "
            "and shade that feels like a gift from the earth itself. "
            "I'm going to build a small clay oven right here by the water. "
            "Flatbread with sesame, roasted dates, and mint tea — "
            "the desert's own feast. Tonight, when the stars come out — "
            "and out here they come out by the millions — we'll eat like ancient travelers "
            "who knew the real luxury was simply arriving alive.\""
        ),
        "summary": "Oasis no deserto e cenario romantico e cinematografico. Contraste entre aridez do deserto e abundancia do oasis. Cha de menta e pao flatbread sao autenticamente acolhedores.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "MEDIA",
    },
    {
        "num": 17,
        "title": "Snowbound in a Mountain Shepherd's Hut: Slow-Cooked Lamb Stew & Fresh Cheese | Ghibli-Style ASMR",
        "hook": (
            "[Sound of sheep bells in distance, howling wind, wooden door rattling] "
            "\"The pass is blocked. We're staying the night.\" [Sound of heavy door opening, warmth rushing in] "
            "\"This shepherd's hut has been here for a hundred years. Stone walls so thick "
            "not even the coldest wind can get through. There's dried wood stacked in the corner "
            "and a cast iron pot hanging over the hearth. I have lamb, root vegetables, "
            "and herbs I picked on the trail this morning. And look — "
            "the shepherd left fresh cheese wrapped in cloth. "
            "We'll cook slowly, eat gratefully, and let the mountain decide when to let us go.\""
        ),
        "summary": "Cabana de pastor na montanha com neve e cenario de aventura segura. Ensopado de cordeiro lento e queijo fresco evocam autenticidade. Cenario europeu expande a audiencia.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "MEDIA",
    },
    {
        "num": 18,
        "title": "Camping on a Frozen Lake: Ice Fishing & Cooking the Catch in a Warm Tent | Ghibli-Style ASMR",
        "hook": (
            "[Sound of boots crunching on thick ice, wind sweeping across the frozen surface, distant cracks] "
            "\"It's solid. We're good.\" [Sound of ice auger drilling through, water bubbling up] "
            "\"There's something magical about standing on top of a lake. "
            "An entire world of fish swimming beneath your feet while the sky stretches forever above. "
            "I've set up our tent right here — the small stove is already warming it up inside. "
            "Let's drop the line, wait patiently, and when we catch our dinner, "
            "I'll cook it right here in the tent with butter, lemon, and fresh dill. "
            "The best restaurant has no walls and no menu — just what the lake gives us.\""
        ),
        "summary": "Pesca no gelo e culinaria na tenda combinam aventura com conforto. Lago congelado e visualmente impressionante. Pescar e cozinhar o proprio peixe tem alto apelo de autossuficiencia.",
        "pillar": "Culinaria e Vida Extrema",
        "priority": "MEDIA",
    },
    # =========================================================================
    # PILAR 3: Nostalgia e Familia (15%) — 5 ideas
    # =========================================================================
    {
        "num": 19,
        "title": "Go Back to Childhood: A Peaceful Day at Grandma's House, Picking Persimmons & Making Jam | Ghibli Cozy Life",
        "hook": (
            "[Sound of old wooden gate creaking, birds singing, gentle breeze] "
            "\"Grandma? I'm here...\" [Sound of footsteps on packed earth, dry leaves crunching] "
            "\"Every time I open this gate, it feels like time rewinds twenty years. "
            "The smell of the earth, the white curtains on the window... everything is the same. "
            "Look at the persimmon tree, it's so full this year. "
            "Grandma always said the sweetest fruits are the ones that ripen slowly. "
            "Today I'll pick the prettiest ones and make that jam she taught me. "
            "Every time I stir the pot, it's like she's right here beside me again.\""
        ),
        "summary": "Video nostalgico que conecta espectador com memorias de infancia na casa dos avos. Colher caqui e fazer geleia sao atividades sensoriais ricas. Alto engajamento em comentarios e compartilhamento.",
        "pillar": "Nostalgia e Familia",
        "priority": "ALTA",
    },
    {
        "num": 20,
        "title": "The Winters I Never Forgot: Making Sweet Potato Soup with Grandma by the Wood Stove | Ghibli-Style Video",
        "hook": (
            "[Sound of wood stove crackling intensely, winter wind outside, ceramic bowls clinking] "
            "\"Careful with the lid, dear. The steam will bite your fingers.\" [Sound of pot lid lifted, rush of fragrant steam] "
            "\"Every winter, grandma would peel sweet potatoes by the stove "
            "while telling me stories about when she was young. "
            "Her hands moved so slowly, so carefully — as if each potato held a secret inside. "
            "'The best soup,' she'd say, 'is the one made while you're telling stories.' "
            "Today I'm standing in her kitchen. Same stove. Same pot. "
            "And I swear I can still hear her voice in the crackling of the fire.\""
        ),
        "summary": "Memoria direta com avo e receita herdada criam conexao emocional profunda. Batata doce + fogao a lenha sao iconicos. Formato 'Ghibli-Style Video' para animacao pura.",
        "pillar": "Nostalgia e Familia",
        "priority": "ALTA",
    },
    {
        "num": 21,
        "title": "When Christmas Brought You Home: Wrapping Gifts & Baking Cookies with Family | Ghibli Cozy Life",
        "hook": (
            "[Sound of music box playing a Christmas melody, wrapping paper crinkling, children laughing in another room] "
            "\"You made it. We've been waiting for you.\" [Sound of warm hug, coat being removed, door closing out the cold] "
            "\"The tree is up. The kids helped decorate it — can you tell? "
            "Ornaments everywhere, including the floor. The kitchen smells like butter and cinnamon "
            "because we started the cookies without you. Sorry. Come, put on this apron. "
            "Your cookie shapes were always the funniest ones. "
            "Tonight, after dinner, we'll sit by the tree and just be together. "
            "That's all Christmas really is, isn't it? Just... being together.\""
        ),
        "summary": "Natal em familia e tema universal com pico de busca sazonal massivo. Biscoitos e presentes sao visuais e ASMR perfeitos. Video projetado para dezembro com apelo global.",
        "pillar": "Nostalgia e Familia",
        "priority": "ALTA",
    },
    {
        "num": 22,
        "title": "A Letter from Dad: Reading Old Recipes & Cooking His Favorite Curry on a Rainy Day | Ghibli-Style Video",
        "hook": (
            "[Sound of rain tapping on glass, old drawer sliding open, paper rustling] "
            "\"I found it... in the back of the kitchen drawer.\" [Sound of envelope being carefully opened, a quiet breath] "
            "\"Dad's handwriting. I'd recognize it anywhere — the way he wrote his 'r's "
            "always looked like tiny mountains. It's his curry recipe. "
            "The one he made every Sunday when I was small. "
            "He never measured anything — just 'a pinch of this, a handful of that.' "
            "But I remember the smell. I remember everything. "
            "Today I'm going to follow his words exactly, rain on the window just like he liked, "
            "and cook this curry until the whole house smells like a Sunday in 1998.\""
        ),
        "summary": "Carta do pai com receita manuscrita ativa nostalgia profunda. Curry como prato afetivo e universal. Video emocional projetado para alto compartilhamento e comentarios emocionados.",
        "pillar": "Nostalgia e Familia",
        "priority": "MEDIA",
    },
    {
        "num": 23,
        "title": "Summer at Grandpa's Farm: Catching Fireflies & Making Watermelon Ice Pops | Ghibli Cozy Life",
        "hook": (
            "[Sound of cicadas singing, warm evening breeze, bare feet on grass] "
            "\"Grandpa, look! There's one!\" [Sound of small glass jar opening, soft glow reflecting] "
            "\"He always said fireflies only come out when the day was truly good. "
            "Like they're little thank-you lights from the earth. The watermelons he grew this summer "
            "are the biggest I've ever seen. He cut one open this morning and the inside was so red "
            "it looked like a sunset. I'm going to blend it into ice pops "
            "the way mom used to — simple, sweet, and cold enough to make your teeth tingle. "
            "When the sun goes down, we'll chase fireflies until the jar glows like a lantern.\""
        ),
        "summary": "Verao no sitio do avo e nostalgia de infancia pura. Vagalumes e melancia sao iconicos de verao japones/Ghibli (Grave of the Fireflies vibes). Video leve para variar do inverno.",
        "pillar": "Nostalgia e Familia",
        "priority": "MEDIA",
    },
    # =========================================================================
    # PILAR 4: Vida Solitaria / Slow Living (15%) — 5 ideas
    # =========================================================================
    {
        "num": 24,
        "title": "A Quiet Week Living Alone: Slow Mornings, Cooking for One & Finding Peace in Solitude | Ghibli Cozy Life",
        "hook": (
            "[Sound of gentle alarm, sheets being pulled, feet touching wooden floor] "
            "\"Good morning...\" [Sound of curtain being opened, light streaming in, a quiet sigh] "
            "\"No one waiting. No urgent messages. Just me and this silent morning. "
            "There's something beautiful about making coffee just for yourself. "
            "About choosing your favorite mug without rushing. "
            "About hearing the water boil while the world outside is still asleep. "
            "This week, I decided to do nothing beyond what's necessary. "
            "Cook slowly, read by the window, and let silence be the best company. "
            "Come with me?\""
        ),
        "summary": "Vida solitaria com rotinas simples ressoa fortemente com jovens adultos urbanos introvertidos. Cozinhar para um e tema com identificacao direta. Inspirado no MokalMusic (360K views).",
        "pillar": "Vida Solitaria / Slow Living",
        "priority": "ALTA",
    },
    {
        "num": 25,
        "title": "Rainy Sunday Alone: Reorganizing My Little Kitchen & Making Comfort Pasta | Ghibli Cozy Life",
        "hook": (
            "[Sound of persistent rain, coffee percolating, cabinet doors opening and closing gently] "
            "\"I've been putting this off for weeks.\" [Sound of jars clinking, spices being sorted] "
            "\"There's a special kind of peace in organizing when it rains outside. "
            "Every jar in its place, every spoon where it belongs. "
            "My little kitchen is small but it's mine, and today it gets the love it deserves. "
            "And when everything is perfectly in place, I'll reward both of us — "
            "me and this kitchen — with the simplest, most comforting pasta. "
            "Garlic, olive oil, parmesan, and a pinch of chili. Nothing fancy. Just... honest.\""
        ),
        "summary": "Organizar a cozinha + cozinhar sozinho(a) combina satisfacao de organizacao com slow living. Domingo chuvoso e momento universal de introspecao. Pasta simples e reconfortante.",
        "pillar": "Vida Solitaria / Slow Living",
        "priority": "MEDIA",
    },
    {
        "num": 26,
        "title": "Moving to the Countryside: My First Morning in a New Life of Simplicity | Ghibli Cozy Life",
        "hook": (
            "[Sound of rooster crowing in the distance, morning dew dripping, creaky new-old door opening] "
            "\"This is it. This is really happening.\" [Sound of first steps on porch, deep breath of fresh air] "
            "\"Yesterday I was in a city of ten million people. Today... I can hear individual birds. "
            "The boxes aren't unpacked yet. The kitchen has nothing but a kettle and two cups. "
            "But the view from this window... fields as far as you can see, "
            "and a sky so big it makes you feel small in the most beautiful way. "
            "I'm going to boil water for tea, sit on this porch, "
            "and let the silence teach me how to breathe again. This is day one.\""
        ),
        "summary": "Mudar para o campo e sonho de escapismo que o publico projeta em si mesmo. Primeiro dia em nova vida e narrativa poderosa. Simplicidade radical ressoa com audiencia urbana exausta.",
        "pillar": "Vida Solitaria / Slow Living",
        "priority": "ALTA",
    },
    {
        "num": 27,
        "title": "Night Shift Worker's Day Off: Sleeping Until Noon & Cooking a Late Brunch | Ghibli Cozy Life",
        "hook": (
            "[Sound of alarm being silenced, blankets rustling, deep satisfied sigh] "
            "\"Not today. Today I sleep.\" [Sound of blinds blocking the sun, settling back into pillow] "
            "\"...\" [Time skip sound — clock ticking, sun moving across the room] "
            "\"Noon. The best word in the English language when you work nights. "
            "No alarm, no schedule, no one needs me for the next twenty-four hours. "
            "I'm going to make the brunch I never have time for — eggs benedict with hollandaise, "
            "fresh orange juice, and toast so crispy it echoes in the kitchen. "
            "This is what living alone gives you: the luxury of a slow, unbothered afternoon.\""
        ),
        "summary": "Trabalhador noturno em dia de folga e nicho ultraespecifico com alta identificacao. Brunch tardio e indulgencia acessivel. Conecta com audiencia de jovens trabalhadores exaustos.",
        "pillar": "Vida Solitaria / Slow Living",
        "priority": "MEDIA",
    },
    {
        "num": 28,
        "title": "A Rainy Evening Alone with My Cat: Making Onigiri & Reading by Candlelight | Ghibli Cozy Life",
        "hook": (
            "[Sound of steady rain, cat purring on a cushion, pages turning slowly] "
            "\"You're not going anywhere either, are you?\" [Sound of cat meowing softly, stretching] "
            "\"Rainy evenings were made for this. No plans, no people — just me, you, "
            "and a book I've been meaning to finish for months. "
            "But first, dinner. Something simple. Onigiri — "
            "rice pressed with warm hands, filled with pickled plum and wrapped in seaweed. "
            "The kind of food that doesn't try to impress anyone. "
            "It just... nourishes. Like this silence. Like this rain. Like you, little one.\""
        ),
        "summary": "Gato + chuva + solidao confortavel e combinacao perfeita para o publico-alvo. Onigiri e icone japones e Ghibli. Ler a luz de velas adiciona camada sensorial unica.",
        "pillar": "Vida Solitaria / Slow Living",
        "priority": "ALTA",
    },
    # =========================================================================
    # PILAR 5: Colheita e Natureza Sazonal (10%) — 2 ideas
    # =========================================================================
    {
        "num": 29,
        "title": "Harvesting Wild Mushrooms in the Autumn Forest: Cooking Over an Open Fire by the River | Ghibli-Style ASMR",
        "hook": (
            "[Sound of footsteps on crunchy dry leaves, distant birds, stream in the background] "
            "\"Look at this one... perfect.\" [Sound of mushroom being delicately pulled from damp earth] "
            "\"Autumn turns the entire forest into a pantry. You just need to know where to look. "
            "My grandfather taught me to recognize the good mushrooms by their smell — "
            "earthy, with a hint of chestnut. Today I found a special spot near the river. "
            "I'll light a fire there between the stones and prepare everything right here, "
            "with fresh water from the stream. No restaurant in the world "
            "serves anything as honest as this.\""
        ),
        "summary": "Forrageamento de cogumelos e sub-nicho em ascensao no YouTube. Outono + culinaria ao ar livre conectam natureza com comida. Cenario de rio e floresta com tons outonais e visualmente lindo.",
        "pillar": "Colheita e Natureza Sazonal",
        "priority": "MEDIA",
    },
    {
        "num": 30,
        "title": "Spring Harvest in the Mountain Garden: Picking Herbs, Radishes & Making a Fresh Salad | Ghibli-Style ASMR",
        "hook": (
            "[Sound of morning dew dripping, soil being gently turned, bees buzzing nearby] "
            "\"The garden woke up before me today.\" [Sound of hands brushing soil off a radish, a satisfied hum] "
            "\"After months of frost, the earth is finally giving back. "
            "Look at these radishes — so pink and firm, like little jewels hidden in the dirt. "
            "The herbs are going wild too — basil, mint, thyme — "
            "they smell like the whole garden is cooking itself. "
            "Today everything goes straight from the soil to the bowl. "
            "A salad so fresh you can taste the morning in every bite. "
            "No supermarket, no plastic, no rush. Just the garden and patience.\""
        ),
        "summary": "Colheita de primavera no jardim da montanha celebra o ciclo sazonal. Rabanetes e ervas sao visualmente atraentes. Salada fresca direto da terra conecta com vida simples e autossuficiente.",
        "pillar": "Colheita e Natureza Sazonal",
        "priority": "MEDIA",
    },
]


def main() -> None:
    for idea in IDEAS:
        save_idea(
            project_id=PROJECT_ID,
            num=idea["num"],
            title=idea["title"],
            hook=idea["hook"],
            summary=idea["summary"],
            pillar=idea["pillar"],
            priority=idea["priority"],
        )
    print(f"Saved {len(IDEAS)} ideas for project '{PROJECT_ID}'.")


if __name__ == "__main__":
    main()
