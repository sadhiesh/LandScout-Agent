# Criteria Parsing Skill

## Purpose

Parse natural language land search requests into structured SearchCriteria for LandWatch search. Extract only explicitly mentioned criteria, leaving unmentioned fields as null.

## Usage

Load this skill when parsing user requests in the Supervisor agent. The skill provides the prompt template for extracting search criteria from natural language.

## Prompt Template

Use this template with `{user_message}` replaced by the actual user request:

```
<!-- BEGIN turn_resolution -->
Extract land search criteria from this request:

"{user_message}"

Current criteria from this session:
{current_criteria_json}

Current scored results, if any:
{current_results_json}

First classify this turn:
- "search": start or amend a search.
- "reset": explicitly discard prior criteria and start over.
- "results_question": answer a question about current results (shortlist or 
  candidates) without changing the search. Use only the supplied result facts;
  do not invent facts. Questions like "why only 25?", "what's the average price?",
  "tell me about the results" are results_question, not search.
  If no results were supplied at all, classify it as "search".
- "off_topic": user asks about something unrelated to land/real estate/property
  search (e.g., weather, sports, general knowledge). Set _answer to a polite
  redirect: "I specialize in land searches. I can help you find properties by
  location, price, acreage, or type. What kind of land are you looking for?"
- "conversational": general questions about the system, how it works, or 
  clarifications (e.g., "how does this work?", "what can you do?"). Set _answer
  to a helpful explanation focused on land search capabilities.

For search amendments, extract ONLY what the user explicitly changed or added.
Set other criteria fields to null so the caller can preserve prior values.
List a field in "_clear_fields" when the user explicitly removes it or when a
new range makes an old bound invalid. Example: "5 acres and above" sets
acres_min=5 and clears acres_max.
Do not clear a field that also has a non-null replacement in this patch.
For example, changing Weston to Roland sets city="roland" without clearing city.

LOCATION (mutually exclusive - pick the most specific):
  state: full name or code (texas, TX)
  county: county name only if user said county (collin, not 'Collin County')
  city: city name if user mentioned a specific city (mckinney, dallas, austin)
  region: region name only if mentioned (texoma, hill-country)

SIZE & PRICE:
  acres_min, acres_max: extract from '15-20 acres', '20+ acres', 'under 50 acres'
  price_min, price_max: extract from 'under $1M' (max only), 'over $500k' (min only)
  sqft_min, sqft_max: house square footage if mentioned
  beds_min, baths_min: minimum bedrooms/baths if house is mentioned

PROPERTY TYPE (extract if mentioned):
  property_types: {property_type_values}

FEATURES (extract if mentioned):
  keyword: free text for PHYSICAL LAND features and qualities only — e.g.
    'creek access', 'timber', 'cleared', 'fenced', 'waterfront features',
    'pond', 'view', 'hilltop', 'wooded'. Never use keyword for the buyer's
    purpose, motive, or financing intent (investment, resale, flip, profit,
    personal use, quick sale, cash buyer). Those are NOT land features.
  activities: {activity_values}
  geographies: {geography_values}
  land_uses: {land_use_values}
  housing_types: {housing_type_values}

REQUIREMENTS (boolean, extract if mentioned):
  has_residence: true (wants house), false (no house), null (doesn't care)
  owner_financing: true if they want owner financing
  mineral_rights: true if they want to retain mineral rights
  hoa: 'none', 'mandatory', 'voluntary', or null

RULES:
  - 'in [city]' -> extract city, NOT county
  - 'under $X' -> price_max=$X, price_min=0
  - 'over $X' -> price_min=$X, price_max=null
  - 'hunting land' -> property_types=['hunting'] AND activities=['hunting']
  - 'with creek' -> keyword='creek'
  - Use structured fields (property_types, activities, geographies, land_uses, 
    housing_types) when the user's term exactly matches a supported value
  - For feature modifiers or qualities ('waterfront features', 'pond', 'creek 
    access'), use keyword field instead of structured fields
  - 'waterfront property' as a type -> property_types=['waterfront']
  - 'with waterfront features' as a quality -> keyword='waterfront'
  - 'its for investment / resale / flipping / personal use / quick sale' ->
    purpose statement only, not a land feature; leave keyword null
  - DO NOT set keyword from the buyer's goal, motive, or financing plan
  - DO NOT invent criteria the user didn't mention
  - DO NOT infer has_residence=false from 'undeveloped land' alone; only set it 
    when the user explicitly states they want no residence or must have one

Return ONLY JSON with these exact keys:
{"_turn_intent": "search"|"reset"|"results_question"|"off_topic"|"conversational",
  "_answer": str|null, "_clear_fields": [str],
  "state": str|null, "county": str|null, "city": str|null, "region": str|null,
  "acres_min": num|null, "acres_max": num|null,
  "price_min": num|null, "price_max": num|null,
  "sqft_min": num|null, "sqft_max": num|null,
  "beds_min": num|null, "baths_min": num|null,
  "property_types": [str]|null, "keyword": str|null,
  "activities": [str]|null, "geographies": [str]|null,
  "land_uses": [str]|null, "housing_types": [str]|null,
  "has_residence": bool|null, "owner_financing": bool|null,
  "mineral_rights": bool|null, "hoa": str|null,
  "_stated_fields": [str]}

For "results_question", "off_topic", and "conversational", set "_answer" to a
helpful response and leave all criteria fields null. For "search" and "reset", 
set "_answer" to null.

"_stated_fields" lists only the keys the user EXPLICITLY said. A value you
worked out yourself must be left out of it, even though you still fill the
key in. "McKinney" tells you the state is Texas, but the user did not say
Texas — so set "state": "texas" and leave "state" out of "_stated_fields".
This is how the agent knows which of its own assumptions to confirm.
<!-- END turn_resolution -->
```

## Examples

### Example 1: Simple Location + Size
**Input:** "Find land in Collin County, Texas under $500k, 20-50 acres"

**Output:**
```json
{
  "_turn_intent": "search",
  "_answer": null,
  "_clear_fields": [],
  "state": "texas",
  "county": "collin",
  "city": null,
  "region": null,
  "acres_min": 20,
  "acres_max": 50,
  "price_min": 0,
  "price_max": 500000,
  "sqft_min": null,
  "sqft_max": null,
  "beds_min": null,
  "baths_min": null,
  "property_types": null,
  "keyword": null,
  "activities": null,
  "geographies": null,
  "land_uses": null,
  "housing_types": null,
  "has_residence": null,
  "owner_financing": null,
  "mineral_rights": null,
  "hoa": null,
  "_stated_fields": ["state", "county", "price_max", "acres_min", "acres_max"]
}
```

The user named Texas outright here, so `state` belongs in `_stated_fields`.

### Example 2: Hunting Land with Features
**Input:** "Looking for hunting land in Texas with creek access, 40+ acres"

**Output:**
```json
{
  "_turn_intent": "search",
  "_answer": null,
  "_clear_fields": [],
  "state": "texas",
  "county": null,
  "city": null,
  "region": null,
  "acres_min": 40,
  "acres_max": null,
  "price_min": null,
  "price_max": null,
  "sqft_min": null,
  "sqft_max": null,
  "beds_min": null,
  "baths_min": null,
  "property_types": ["hunting"],
  "keyword": "creek",
  "activities": ["hunting"],
  "geographies": null,
  "land_uses": null,
  "housing_types": null,
  "has_residence": null,
  "owner_financing": null,
  "mineral_rights": null,
  "hoa": null,
  "_stated_fields": ["state", "acres_min", "property_types", "keyword", "activities"]
}
```

### Example 3: Homestead with House
**Input:** "Need a homestead in McKinney with a 3 bed house, 10-15 acres"

**Output:**
```json
{
  "_turn_intent": "search",
  "_answer": null,
  "_clear_fields": [],
  "state": "texas",
  "county": null,
  "city": "mckinney",
  "region": null,
  "acres_min": 10,
  "acres_max": 15,
  "price_min": null,
  "price_max": null,
  "sqft_min": null,
  "sqft_max": null,
  "beds_min": 3,
  "baths_min": null,
  "property_types": null,
  "keyword": null,
  "activities": null,
  "geographies": null,
  "land_uses": ["homestead"],
  "housing_types": null,
  "has_residence": true,
  "owner_financing": null,
  "mineral_rights": null,
  "hoa": null,
  "_stated_fields": ["city", "acres_min", "acres_max", "beds_min", "land_uses", "has_residence"]
}
```

Note what is missing from `_stated_fields`: `state`. "McKinney" is in Texas
and the key is filled in accordingly, but the user never said so, and the
agent should confirm that rather than assume it silently.

### Example 4: Purpose Statement — keyword must be null

**Input:** "its for investment and looking for in collin county"

This turn states an investment *purpose*, not a physical land feature.
`keyword` must stay null — "investment" is not a land descriptor and would
produce meaningless results as a literal listing search term.

**Output:**
```json
{
  "_turn_intent": "search",
  "_answer": null,
  "_clear_fields": [],
  "state": null,
  "county": "collin",
  "city": null,
  "region": null,
  "acres_min": null,
  "acres_max": null,
  "price_min": null,
  "price_max": null,
  "sqft_min": null,
  "sqft_max": null,
  "beds_min": null,
  "baths_min": null,
  "property_types": null,
  "keyword": null,
  "activities": null,
  "geographies": null,
  "land_uses": null,
  "housing_types": null,
  "has_residence": null,
  "owner_financing": null,
  "mineral_rights": null,
  "hoa": null,
  "_stated_fields": ["county"]
}
```

"investment" is the buyer's purpose, not a land feature — `keyword` is null.
`county` is the only stated search constraint.

## Post-Processing

After LLM extraction, the code should:

1. **Validate and normalize location** using `landwatch.places`:
   - Convert state names to slugs (e.g., "texas")
   - Resolve county names to canonical slugs
   - Resolve city names (may require network call)

2. **Build provenance map** from `_stated_fields`, marking each key `user`,
   `inferred`, or `default`. The gate confirms `inferred` locations before
   searching, so collapsing the three into two would hide assumptions.

3. **Apply defaults** only for critical missing fields (e.g., state) from `config/criteria.yaml`

4. **Emit thought event** with parsed criteria and provenance for debugging
