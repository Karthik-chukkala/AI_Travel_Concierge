# Scraping Observations & DOM Analysis

This document details the exact extraction strategy and CSS selectors for parsing HTML/DOM structures from `etrain.info`.

---

## 1. Station-to-Station Trains Data

### Target Page URL
- Without Date: `https://etrain.info/trains/{source_code}-to-{destination_code}`
- With Date: `https://etrain.info/trains/{source_code}-to-{destination_code}?date={date}`

### HTML DOM Structure
Each train row is contained in a `tr` element with a `data-train` attribute inside the main trains list table:
```html
<div class="trainlist rnd5" comb="0">
  <table class="myTable data ...">
    <tr data-train='{"typ":"sf","num":"22605","name":"PRR TEN EXPRESS","s":"VSKP","st":"01:40","d":"TNM","dt":"17:26","tt":"15:46H","dy":"0010001","book":"1","arp":60}' ...>
      ...
      <td class="bold wd191">
        <div class="flexRow f-hvcenter">
          <a class="cavlink pdud2 mglr2" data-ettav='{"tsd":"22605-VSKP-TNM","c":"2A"}' href="#22605-VSKP-TNM-2A">2A</a>
          <a class="cavlink pdud2 mglr2" data-ettav='{"tsd":"22605-VSKP-TNM","c":"3A"}' href="#22605-VSKP-TNM-3A">3A</a>
          <a class="cavlink pdud2 mglr2" data-ettav='{"tsd":"22605-VSKP-TNM","c":"SL"}' href="#22605-VSKP-TNM-SL">SL</a>
        </div>
      </td>
    </tr>
  </table>
</div>
```

### Extraction Strategy (BeautifulSoup)
1. Select all `tr` elements containing the attribute `data-train` using selector:
   `tr[data-train]` (or `.trainlist table tr[data-train]`).
2. Parse the value of the `data-train` attribute as a JSON string.
3. Extract:
   - `num`: Train Number (string)
   - `name`: Train Name (string)
   - `s`: Depart Station Code (string)
   - `st`: Departure Time (string)
   - `d`: Arrival Station Code (string)
   - `dt`: Arrival Time (string)
   - `tt`: Travel Time (string, e.g. "15:46H")
   - `dy`: Running Days (7-character bitstring, e.g. "0010001" where index 0 is Sunday, index 1 is Monday, ..., index 6 is Saturday)
4. Extract classes from links with class `cavlink` within the row:
   - For each `a.cavlink` inside the `tr`, parse its `data-ettav` attribute as JSON.
   - Extract the `"c"` value (representing the class name, e.g., "2A", "3A", "SL", "GN").

### Handling Date Constraints Strictly
When a `date` is requested (e.g. `2026-06-26`):
1. Parse the date using Python's `datetime`.
2. Determine the day of the week.
   - Map Python's `dt.weekday()` (where Monday is 0, Sunday is 6) to the etrain index:
     `etrain_index = (dt.weekday() + 2) % 7` (Saturday becomes 0, Sunday 1, ..., Friday 6).
3. Check if the character at `etrain_index` in `dy` is `'1'`. If not, discard or mark this train as not running on the specified date.

### Fallback Strategy (Pandas)
Use `pandas.read_html(response.text)` to extract the tables.
- Iterate over the read DataFrames.
- Identify the table where columns contain values matching departure/arrival times, station codes, or running days headers.
- Extract columns corresponding to Train Number, Train Name, Depart/Arrival Time, Travel Time, Days, and Classes.

---

## 2. Train Running History / Delay Data

### Target Page URL
- `https://etrain.info/train/{train_number}/history?d={duration}` (where `duration` is typically `'1y'`).

### HTML DOM Structure
Average delay data at each stop is stored in anchors with class `runStatStn`:
```html
<a href="#VSKP" etitle="..." class="runStatStn blocklink rnd5">
  <div>
    VISAKHAPATNAM (VSKP)
    <div class="inlineblock fltright">
      <div class="inlineblock pdl5"><b>Avg. Delay:</b> 85 Min's</div>
    </div>
  </div>
  ...
</a>
```
Alternative/Fallback JavaScript structure containing the raw data:
```javascript
et.rsStat.primaryData = [ 
  ['Stations','Right Time', 'Slight Delay', 'Significant Delay', 'Cancelled/Unknown', {'type': 'string', 'role': 'tooltip', 'p': {'html': true}}],
  ['KGP', 52, 0, 0, 0, 2],
  ...
  ['VSKP', 6, 11, 35, 0, 85.4],
  ...
];
```

### Extraction Strategy (BeautifulSoup)
1. Find all `a` tags with class `runStatStn`:
   - Station Code: Extract from `href` (remove the leading `#`).
   - Suffix clean-up: Remove whitespace.
   - Average Delay: Search the anchor's text for a pattern like `Avg. Delay: (\d+)` or parse the text of sibling tags inside `inlineblock pdl5`.
2. Fallback / script parsing:
   - Search `<script>` tags for the string `et.rsStat.primaryData`.
   - Use regex `\[\s*'([A-Z]+)'\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d\.]+)\s*\]` to match the station code and average delay directly.
3. Combine results into a dictionary mapping `STATION_CODE -> average_delay_minutes` (float/int).

---

## 3. Train Schedule Data

### Target Page URL
- `https://etrain.info/train/{train_number}/schedule`

### HTML DOM Structure
The schedule table resides inside a container `#sublowerdata`:
```html
<div id="sublowerdata" class="bx3_brd">
  <table class="fullw nocps nolrborder bx3_brl">
    <thead>...</thead>
    <!-- Station Stop Row -->
    <tr class="even">
      <td class="txt-center pdud15 dborder nobr">
        <div class="pdl5">2</div>
        <small><div class="pdl5">BLDA</div></small>
      </td>
      <td class="vline nobr"><div class="vcircle">&nbsp;</div></td>
      <td class="pdud15 pdlr5 txt-lt pos-relative dborder nobr intstnCont">
        <div class="fixwelps">BELDA</div>
        <div class="nowrap pos-relative">
          <small><div class="nowrap fixw70">38 kms</div>Platform: 1</small>
        </div>
      </td>
      <td class="txt-center bold bx3_bgl dborder nobr">
        <div class="pdud5 pdlr2">A</div>
        <div class="pdud5 pdlr2">D</div>
      </td>
      <td class="txt-lt dborder">
        <div class="nowrap pd5">14:24 (Day 1)</div>
        <div class="nowrap pd5">14:26 (Day 1)</div>
      </td>
    </tr>
    ...
  </table>
</div>
```

### Extraction Strategy (BeautifulSoup)
1. Select all `tr` elements inside `#sublowerdata table` that contain a `div` with class `fixwelps`.
2. For each row `tr`:
   - **S.No**: Select the text inside the first `td`'s `div` (e.g. text `2`).
   - **Station Code**: Select the text inside the first `td`'s `small`'s `div`.
   - **Station Name**: Select the text inside the third `td`'s `div` with class `fixwelps`.
   - **Distance**: Select the text inside the third `td`'s `small`'s `div` with class `fixw70`.
   - **Timings**: Select the fifth `td` (timings cell).
     - Arrival Time is the text of the first inner `div` with class `nowrap pd5` (e.g., `"14:24 (Day 1)"` or `"Source (Day 1)"`).
     - Departure Time is the text of the second inner `div` with class `nowrap pd5` (e.g., `"14:26 (Day 1)"` or `"Destination (Day 2)"`).
3. Return the parsed schedule as a JSON-serializable list of dictionaries.
