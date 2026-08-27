"""Food taxonomy: canonical categories + verified HCES item-code mappings.

Every mapping below cites its origin:
  * HIGH   - read directly from the HCES 2023-24 FDQ Vol-II questionnaire
             (data/raw/official/hces_item_codes_raw*.txt, pages 24-31).
  * MEDIUM - inferred from adjacent questionnaire rows (flagged for review).
Anything not listed maps to OTHER with LOW confidence - never guessed.

Canonical categories align with Indian dietary staples so HCES consumption,
campus menus and Swiggy cuisines can all be described without forcing.
"""
from __future__ import annotations

# Canonical category set (project-wide).
CATEGORIES = [
    "rice_cereals",     # rice, chira/muri, coarse grains, millets, tapioca
    "wheat_breads",     # atta/wheat, maida, suji, vermicelli
    "dal_pulses",       # arhar, moong, masur, urd, gram, besan
    "vegetables",
    "fruits",
    "dairy",            # milk, curd, ghee, butter, paneer
    "egg",
    "fish",
    "chicken_meat",     # chicken, mutton, beef/buffalo, pork
    "oils_fats",
    "sugar_sweets",     # sugar, jaggery, honey, prepared sweets
    "salt",
    "spices",           # chillies, turmeric, cumin, tamarind ...
    "beverages",        # tea, coffee, packaged drinks
    "served_processed", # cooked meals purchased/received (institutional analog!)
    "other",
]

OTHER = "other"

# Verified measurement units per item code. Default is kg (questionnaire:
# "'*' Unit is Kg. Unless otherwise specified"). Quantity shares must never
# mix units; cross-category comparisons use VALUE instead.
UNIT_MAP: dict[str, str] = {
    "160": "litre",   # milk liquid
    "274": "litre",   # mineral water
    "275": "litre",   # beverage (name garbled in PDF extract - verify)
    "276": "litre",   # beverage (verify)
    "278": "litre",   # beverage (verify)
    "011": "litre",   # soda drinks
    "190": "number",  # eggs
    "216": "number",  # lemon
    "220": "number",  # banana
    "223": "number",  # pineapple
    "224": "number",  # coconut
    "225": "number",  # green coconut
    "270": "number",  # tea cups
    "272": "number",  # coffee cups
    "076": "number",  # cooked meals subsidized
    "280": "number",  # cooked meals purchased
    "281": "number",  # cooked meals free workplace
    "282": "number",  # cooked meals assistance
    "284": "number",  # other served processed food
    # Section 7.1/7.2 items recorded in GRAMS per questionnaire
    "250": "gram", "251": "gram", "252": "gram", "253": "gram",
    "254": "gram", "255": "gram", "256": "gram", "257": "gram",
    "258": "gram", "260": "gram", "261": "gram", "263": "gram",
    "271": "gram",    # tea leaf
    "273": "gram",    # coffee powder
}

# Codes recorded in grams (see UNIT_MAP); kg-equivalent = value * 0.001.
GRAM_CODES = {c for c, u in UNIT_MAP.items() if u == "gram"}


# HCES 2023-24 Level-5 Item_Code -> (item_name, category, confidence).
HCES_ITEM_MAP: dict[str, tuple[str, str, str]] = {
    # --- Section 5.1 cereals -----------------------------------------------
    "061": ("rice - free (PMGKAY)", "rice_cereals", "high"),
    "062": ("wheat/atta - free (PMGKAY)", "wheat_breads", "high"),
    "070": ("coarse grains - free (PMGKAY)", "rice_cereals", "high"),
    "101": ("rice - PDS", "rice_cereals", "high"),
    "102": ("rice - other sources", "rice_cereals", "high"),
    "103": ("chira (flattened rice)", "rice_cereals", "high"),
    "105": ("muri (puffed rice)", "rice_cereals", "high"),
    "106": ("other rice products (khoi/lawa)", "rice_cereals", "high"),
    "107": ("wheat/atta - PDS", "wheat_breads", "high"),
    "108": ("wheat/atta - other sources", "wheat_breads", "high"),
    "110": ("maida", "wheat_breads", "high"),
    "111": ("suji/rawa", "wheat_breads", "high"),
    "112": ("vermicelli (sewai)", "wheat_breads", "high"),
    "114": ("other wheat products", "wheat_breads", "high"),
    "001": ("coarse grains - PDS", "rice_cereals", "high"),
    "002": ("coarse grains - other sources", "rice_cereals", "high"),
    "055": ("jowar & products - PDS", "rice_cereals", "high"),
    "056": ("bajra & products - PDS", "rice_cereals", "high"),
    "057": ("maize & products - PDS", "rice_cereals", "high"),
    "058": ("barley & products - PDS", "rice_cereals", "high"),
    "059": ("ragi & products - PDS", "rice_cereals", "high"),
    "060": ("small millets - PDS", "rice_cereals", "high"),
    "115": ("jowar & products", "rice_cereals", "high"),
    "116": ("bajra & products", "rice_cereals", "high"),
    "117": ("maize & products", "rice_cereals", "high"),
    "118": ("barley & products", "rice_cereals", "high"),
    "121": ("ragi & products", "rice_cereals", "high"),
    "120": ("small millets & products", "rice_cereals", "high"),
    "122": ("other cereals & products", "rice_cereals", "high"),
    "129": ("cereal sub-total", "rice_cereals", "high"),      # subtotal
    "139": ("cereal substitutes (tapioca)", "rice_cereals", "high"),
    # --- Section 5.2 pulses -------------------------------------------------
    "140": ("arhar/tur", "dal_pulses", "high"),
    "141": ("gram - split", "dal_pulses", "high"),
    "142": ("gram - whole", "dal_pulses", "high"),
    "143": ("moong", "dal_pulses", "high"),
    "144": ("masur", "dal_pulses", "high"),
    "145": ("urd", "dal_pulses", "high"),
    "146": ("peas/chickpeas", "dal_pulses", "high"),
    "148": ("other pulses (khesari)", "dal_pulses", "high"),
    "150": ("besan/gram products", "dal_pulses", "high"),
    "152": ("other pulse products (soya chunks)", "dal_pulses", "high"),
    "158": ("pulses - PDS", "dal_pulses", "high"),
    "159": ("pulses sub-total", "dal_pulses", "high"),        # subtotal
    "071": ("pulses - free (PMGKAY)", "dal_pulses", "high"),
    "072": ("gram - free (PMGKAY)", "dal_pulses", "high"),
    # --- Section 5.3 sugar & salt --------------------------------------------
    "073": ("salt - free (PMGKAY)", "salt", "high"),
    "074": ("sugar - free (PMGKAY)", "sugar_sweets", "high"),
    "178": ("salt - PDS", "salt", "high"),
    "170": ("salt - other sources", "salt", "high"),
    "171": ("sugar - PDS", "sugar_sweets", "high"),
    "172": ("sugar - other sources", "sugar_sweets", "high"),
    "173": ("jaggery (gur)", "sugar_sweets", "high"),
    "174": ("candy/misri", "sugar_sweets", "high"),
    "175": ("honey", "sugar_sweets", "medium"),
    "179": ("salt & sugar sub-total", "other", "high"),       # subtotal
    # --- Section 6.1 milk & products -----------------------------------------
    "160": ("milk - liquid", "dairy", "high"),
    "163": ("curd/yogurt", "dairy", "high"),
    "164": ("ghee", "dairy", "high"),
    "165": ("butter", "dairy", "high"),
    "166": ("ice-cream", "dairy", "high"),
    "169": ("milk group sub-total", "dairy", "high"),         # subtotal
    "003": ("paneer", "dairy", "medium"),
    "162": ("milk product (condensed/powder - verify)", "dairy", "low"),
    # --- Section 6.x egg / fish / meat ---------------------------------------
    "190": ("eggs", "egg", "high"),
    "191": ("fish/prawn", "fish", "high"),
    "193": ("beef/buffalo meat", "chicken_meat", "high"),
    "194": ("pork", "chicken_meat", "high"),
    "195": ("chicken", "chicken_meat", "high"),
    "199": ("egg/fish/meat sub-total", "chicken_meat", "high"),  # subtotal
    "192": ("meat (goat/sheep - verify)", "chicken_meat", "low"),
    "196": ("other meat (verify)", "chicken_meat", "low"),
    # --- Section 6.x vegetables ----------------------------------------------
    "200": ("potato", "vegetables", "high"),
    "201": ("onion", "vegetables", "high"),
    "202": ("tomato", "vegetables", "high"),
    "203": ("brinjal", "vegetables", "high"),
    "204": ("radish", "vegetables", "high"),
    "205": ("carrot", "vegetables", "high"),
    "206": ("vegetable (verify)", "vegetables", "low"),
    "207": ("green chillies", "vegetables", "high"),
    "208": ("lady's finger", "vegetables", "high"),
    "210": ("leafy vegetable (verify)", "vegetables", "low"),
    "211": ("cauliflower", "vegetables", "high"),
    "212": ("cabbage", "vegetables", "high"),
    "213": ("gourd/pumpkin", "vegetables", "high"),
    "214": ("peas", "vegetables", "high"),
    "215": ("beans/barbati", "vegetables", "high"),
    "216": ("lemon", "vegetables", "high"),
    "217": ("other vegetables", "vegetables", "high"),
    "219": ("vegetables sub-total", "vegetables", "high"),    # subtotal
    # --- Section 6.x fruits ---------------------------------------------------
    "220": ("banana", "fruits", "high"),
    "221": ("jackfruit", "fruits", "medium"),
    "222": ("watermelon", "fruits", "high"),
    "223": ("pineapple", "fruits", "high"),
    "224": ("coconut", "fruits", "high"),
    "225": ("green coconut", "fruits", "high"),
    "226": ("guava", "fruits", "high"),
    "230": ("papaya", "fruits", "high"),
    "231": ("mango", "fruits", "high"),
    "232": ("kharbooza/muskmelon", "fruits", "high"),
    "233": ("pears/nashpati", "fruits", "medium"),
    "234": ("berries", "fruits", "medium"),
    "235": ("litchi", "fruits", "medium"),
    "236": ("apple", "fruits", "high"),
    "237": ("grapes", "fruits", "high"),
    "238": ("other fruits fresh", "fruits", "medium"),
    "239": ("fruits fresh sub-total", "fruits", "high"),      # subtotal
    "240": ("coconut - copra", "fruits", "high"),
    "241": ("groundnut", "fruits", "high"),
    "242": ("dates", "fruits", "high"),
    "243": ("cashew nut", "fruits", "high"),
    "245": ("dry fruit (raisin/walnut - verify)", "fruits", "low"),
    "246": ("dry fruit (verify)", "fruits", "low"),
    "247": ("other fruits dry", "fruits", "medium"),
    "249": ("fruits dry sub-total", "fruits", "high"),        # subtotal
    # --- Section 6.x edible oil ------------------------------------------------
    "180": ("vanaspati/margarine", "oils_fats", "medium"),
    "181": ("mustard oil", "oils_fats", "high"),
    "182": ("groundnut oil", "oils_fats", "high"),
    "183": ("coconut oil", "oils_fats", "high"),
    "184": ("other edible oil (verify)", "oils_fats", "low"),
    "185": ("edible oil others", "oils_fats", "medium"),
    "188": ("edible oil - PDS", "oils_fats", "high"),
    "189": ("edible oil sub-total", "oils_fats", "high"),     # subtotal
    "075": ("edible oil - free (PMGKAY)", "oils_fats", "high"),
    # --- Section 7.1 spices (recorded in grams) ---------------------------------
    "250": ("ginger (gm)", "spices", "high"),
    "251": ("garlic (gm)", "spices", "high"),
    "252": ("cumin/jeera (gm)", "spices", "high"),
    "253": ("spice (coriander? - verify)", "spices", "low"),
    "254": ("turmeric (gm)", "spices", "high"),
    "255": ("black pepper (gm)", "spices", "high"),
    "256": ("dry chillies (gm)", "spices", "high"),
    "257": ("tamarind (gm)", "spices", "high"),
    "258": ("curry powder/misc spice (gm) - verify", "spices", "low"),
    "260": ("oilseeds (gm)", "spices", "high"),
    "261": ("other spices (gm)", "spices", "high"),
    "263": ("poppy seeds (gm)", "spices", "high"),
    "269": ("spices sub-total", "spices", "high"),            # subtotal
    # --- Section 7.2 beverages ---------------------------------------------------
    "270": ("tea - cups", "beverages", "high"),
    "271": ("tea - leaf (gm)", "beverages", "high"),
    "272": ("coffee - cups", "beverages", "high"),
    "273": ("coffee - powder (gm)", "beverages", "high"),
    "274": ("mineral water", "beverages", "high"),
    "275": ("beverage (juice? - verify)", "beverages", "low"),
    "276": ("beverage (soft drink? - verify)", "beverages", "low"),
    "278": ("beverage (other? - verify)", "beverages", "low"),
    "011": ("soda drinks", "beverages", "medium"),
    "279": ("beverages sub-total", "beverages", "high"),      # subtotal
    # --- Section 8.1 served processed food (meal counts!) ------------------------
    "076": ("cooked meals - subsidized rate", "served_processed", "high"),
    "280": ("cooked meals purchased", "served_processed", "high"),
    "281": ("cooked meals - free at workplace", "served_processed", "high"),
    "282": ("cooked meals - assistance/free", "served_processed", "high"),
    "283": ("packed processed food (verify)", "served_processed", "low"),
    "284": ("other served processed food", "served_processed", "high"),
    "289": ("served processed food sub-total", "served_processed", "high"),  # subtotal
    # --- ambiguous internal codes (present in data, unclear meaning) --------------
    "092": ("DDM aggregate (unclear)", "other", "low"),
    "093": ("DDM aggregate (unclear)", "other", "low"),
    "094": ("DDM aggregate (unclear)", "other", "low"),
    "095": ("DDM aggregate (unclear)", "other", "low"),
    "004": ("prepared sweets (milk-based? - verify)", "sugar_sweets", "low"),
    "005": ("cheese (verify)", "dairy", "low"),
    "006": ("lassi", "dairy", "medium"),
    "007": ("buttermilk", "dairy", "medium"),
    "167": ("milk others", "dairy", "medium"),
}

SUBTOTAL_CODES = {c for c, (_, _, _) in HCES_ITEM_MAP.items()
                  if "sub-total" in HCES_ITEM_MAP[c][0]}
# Ambiguous internal aggregates present in the data: excluded from any sum.
EXCLUDE_CODES = SUBTOTAL_CODES | {"092", "093", "094", "095"}
LOW_CONFIDENCE_CODES = [c for c, (_, _, conf) in HCES_ITEM_MAP.items() if conf == "low"]


def map_item(code: str) -> tuple[str, str, str]:
    """-> (item_name, category, confidence); unknowns -> ('unknown', other, low)."""
    hit = HCES_ITEM_MAP.get(str(code).zfill(3))
    return hit if hit else ("unknown", OTHER, "low")


def unit_for(code: str) -> str:
    return UNIT_MAP.get(str(code).zfill(3), "kg")


# Transparent keyword -> category table for restaurant cuisine/dish strings.
CUISINE_KEYWORDS: dict[str, str] = {
    "biryani": "rice_cereals", "south indian": "rice_cereals",
    "north indian": "wheat_breads", "roll": "wheat_breads",
    "paratha": "wheat_breads", "naan": "wheat_breads",
    "dal": "dal_pulses",
    "chicken": "chicken_meat", "kebab": "chicken_meat", "mutton": "chicken_meat",
    "fish": "fish", "seafood": "fish",
    "egg": "egg",
    "ice cream": "dairy", "desserts": "sugar_sweets", "mithai": "sugar_sweets",
    "bakery": "sugar_sweets", "beverages": "beverages", "tea": "beverages",
    # added 2026-08-24 from Swiggy token-frequency audit (top unmapped tokens);
    # only uncontroversial staple-based mappings — ambiguous cuisines
    # (fast food, continental, thali, mughlai…) deliberately stay unmapped.
    "pizza": "wheat_breads",          # flatbread base
    "juice": "beverages",
    "salad": "vegetables",
    "sweet": "sugar_sweets",          # covers "sweets"
}


def map_cuisine_token(token: str) -> str | None:
    t = token.strip().lower()
    for kw, cat in CUISINE_KEYWORDS.items():
        if kw in t:
            return cat
    return None
