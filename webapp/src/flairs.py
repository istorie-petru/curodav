"""Item 10 (2026-09-27), Peter's queued list: "google-calendar-flairs/ ...
is the reference for a new feature: dynamically attach a photo to an
event/task/habit/label/group/project based on a keyword list matched
against its name (a big-but-reasonable keyword list per photo)."

2026-09-27, follow-up (direct correction): the first version of this
feature bundled 79 real photos straight from that reference folder
into `webapp/src/static/flairs/` and shipped them in the repo. Peter
caught a real problem with that: those photos are Google's own
production "flairs" images (https://gstatic.com/tmly/.../flairs/...) --
copyrighted material this project has no license to redistribute, bundle,
or ship in a public repo, self-hosted app or not. Nothing here ships a
single photo byte anymore. What ships instead:

  - `FLAIR_KEYWORDS` below -- pure keyword DATA, not an image. Built from
    the reference folder's own `mapping.csv` (310 rows, real keyword
    research Peter had already done against Google's real feature) plus a
    modest set of additional synonyms (deduced from each photo's own
    FILENAME and existing keywords only, never by viewing an image --
    confirmed via AskUserQuestion; see the git history on this file's
    previous version for the exact reasoning/exclusions, still valid,
    just not re-copied here to keep this docstring from growing forever).
  - A DYNAMIC photo source instead of a bundled one: `configure()` below
    points this module at a directory the operator supplies themselves
    (`Settings.flairs_dir`, `CC_FLAIRS_DIR` -- defaults next to the
    SQLite cache, same "outside the installed app, inside the user's own
    persistent data directory" convention `CC_BACKUP_DIR`/
    `CC_PHOTO_CACHE_DIR` already established in config.py, deliberately
    NOT `webapp/src/static/` -- that directory ships with the app/gets
    replaced on every deploy, exactly the "symlink space" this must
    avoid). `flair_image_url` below only ever returns a URL for a flair
    id whose file the operator has actually placed there themselves --
    see `documentation/flairs.md` for the full supported id list and
    exactly where to put files, including which id needs which filename.
    An id with no file on disk simply contributes no banner anywhere
    (same as it never matched at all) -- this is not an error state, a
    fresh install has zero photos configured until the operator adds
    some, same as a fresh install has no uploaded banners either.

  The four reference season photos (spring/summer/autumn/winter), and
  later the 12 month photos, are deliberately not KEYS in this table --
  matched by DATE, not name, so there's no `FLAIR_KEYWORDS["summer"]`
  entry to string-match against an object's title (see the 2026-09-29
  note further down for the full history and why). They DO still use
  this module's `flair_image_url` as their actual photo source, though
  (2026-09-29, direct request) -- db.py's `banner_for_object` calls it
  directly with the season/month word as the id, bypassing `match_flair`
  entirely, so an operator drops `summer.jpg`/`july.jpg` under
  `flairs_dir` exactly like any other flair and it's picked up with no
  code here even aware those ids aren't real dict keys.

Each entry is `(keyword, priority)`; `priority` is the reference data's
own confidence-ish ranking (2 = its dominant, most-confident tier, up to
5 for its loosest fuzzy matches) -- `match_flair` below uses it as the
tie-break when an object's name contains more than one keyword,
confirmed via AskUserQuestion as the tie-break rule to use (rather than,
e.g., preferring the longest matching phrase). Every keyword this file
adds on top of the reference data (never present there) is priority 2,
the reference data's own dominant tier -- there's no principled way to
reproduce whatever the original research did to arrive at 3/4/5 for its
own harder cases, so new entries just join its most-confident tier
rather than inventing a new meaning for the scale.

Flair ids (this file's own dict keys, and the filename an operator
places under `flairs_dir`) are kebab-case (`american-football`, not the
reference data's own jammed-together `americanfootball`) -- renamed in
this same follow-up, deliberately NOT mirroring Google's own internal
flair-id spelling, since this table is no longer a thin wrapper around
their asset naming at all once the actual bytes stopped coming from
them.

2026-09-29 (direct request: "update the keywords to cover all files in
the folders", after the reference folder was itself reorganized/renamed
into flairs-dir-ready photos + icons/ + unmatched/) -- 24 more flair ids
added on top of the original 79, covering every file that folder
reorganization turned up:

  - 18 real event-type icons Google's own asset set has that the
    original 336-row keyword research never covered (no CSV row at all,
    not even an "unmatched" one): `bills`, `bus`, `delivery`, `doctor`,
    `flight`, `hotel`, `interview`, `kids-pickup-dropoff`,
    `online-classes`, `party`, `photography`, `shopping`, `studying`,
    `trip`, `tv`, `video-call`, `vote`, `gymnastics-generic` (a fallback
    below the two specific gymnastics disciplines -- see its own low
    priority note). Five of these (`bus`, `doctor`, `flight`,
    `shopping`, `trip`/`travel`/`travelling`, `video-call`) DO have a
    literal row in the reference `mapping.csv`, just with `status=
    unmatched` (no flair existed for them yet) -- those exact phrases
    are reused verbatim rather than invented.
  - `restaurant` split out of `dinner` as its own id (confirmed via
    AskUserQuestion despite the reference data itself mapping
    "restaurant"/"restaurants" to `dinner` -- Google ships a visually
    distinct icon for it, and the operator wanted the two kept separate
    even though their keyword lists now necessarily overlap in intent).
    `dinner` no longer claims those two keywords -- see its own entry.

  - 8 scenery/color backgrounds (`university`, `museum`, `debate`,
    `mountain`, `sea`, `sky`, `wood`, `blue`) added despite being common
    English words (a person named "June" isn't a risk here since none of
    these ARE calendar words, but "feeling blue"/"clear sky" etc. still
    can false-positive) -- accepted via AskUserQuestion, priority 5 (the
    loosest tier) on all 8 so `match_flair`'s tie-break always prefers a
    more specific competing match on the same name where one exists.

    Months and seasons are deliberately NOT in this table at all, even
    though the reorganized reference folder has a photo for each --
    direct correction after an initial version of this same slice DID
    add them here as priority-5 keywords (`"march"`, `"summer"`, ...).
    That was wrong for a reason specific to these two categories and
    not the 8 scenery words above: a month/season isn't really a
    *keyword* an event's name happens to contain, it's a property of
    the event's own due/start DATE, which db.py already computes
    directly (no string-matching needed or wanted). Keyword-matching
    "June" against an event's title is both redundant with that (most
    June-dated events don't say "June" in the title, and the ones that
    do already resolve correctly via the date) and a pure false-positive
    generator for the ones that don't.

    That said (same day, direct follow-up: "the months/seasons should
    work through the flairs system, even the default ones") they DO use
    `flair_image_url` below as their photo source -- db.py's
    `banner_for_object` calls it with the exact id `season_for_date`/
    `month_for_date` computed ("summer", "july", ...), same function
    every keyword flair's match already resolves through, just never via
    `match_flair`/this dict. An operator drops `summer.jpg`/`july.jpg`
    into `flairs_dir` -- this reorganized folder's root now has all 16
    (the season/month photos moved back there from a short-lived
    `seasonal/` subfolder once this landed) -- and it's picked up with
    zero code changes needed here, `flair_image_url` has no idea these
    ids aren't real `FLAIR_KEYWORDS` keys. An explicit per-scope banner
    set through the normal /banners/editor still overrides it, same
    priority order as every other flair default (see db.py's
    `banner_for_object` docstring for the exact tier order).

  - Deliberately did NOT add `.svg` to `SUPPORTED_EXTENSIONS`, even
    though every one of the 18 event-type icons above only exists as an
    SVG in Google's own set (no jpg/png/webp equivalent was ever
    downloaded for them) -- so those 18 new ids match keywords
    correctly but `flair_image_url` will keep returning None for all of
    them until the operator supplies a real raster file, exactly as if
    no file had been placed at all. This isn't an oversight: `image_
    sniff.sniff_image_type` (this app's whole reason for re-sniffing
    bytes instead of trusting an extension, see that module's own
    docstring) only allowlists jpeg/png/gif/webp magic bytes, and SVG is
    an XML format that can embed `<script>`/event-handler content -- an
    app with no auth (see webapp/README.md's "Known gaps") serving
    arbitrary operator-placed SVGs as `image/svg+xml` is a real
    stored-XSS surface if that response is ever embedded somewhere a
    browser executes it, unlike the four binary formats already
    allowlisted. Adding `.svg` here without also teaching `sniff_
    image_type` to validate (or sanitize) SVG content would have made
    `flair_image_url` claim a photo exists while the serving route
    404s on it (sniff returns None) -- silently broken, not silently
    insecure, but still wrong, so this was left alone rather than
    guessed at. `icons/` in the reference folder holds these as-is for
    whoever converts them (rasterize to PNG, or add real SVG
    sanitization + sniffing) -- a deliberate follow-up, not done here."""

from __future__ import annotations

from pathlib import Path

FLAIR_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "american-football": [("american football", 2), ("football", 2), ("gridiron", 2), ("nfl", 2), ("super bowl", 2), ("superbowl", 2)],
    "art": [("art class", 2), ("art workshop", 2), ("art workshops", 2), ("drawing workshop", 2), ("paint night", 2), ("painting", 2), ("sketching workshop", 2)],
    "artistic-gymnastics": [("artistic gymnastics", 2)],
    "athletics-jumping": [("jumping", 2)],
    "baby-shower": [("baby shower", 2), ("babyshower", 2), ("maternity", 2)],
    "back-to-school": [("back to school", 2), ("back2school", 2), ("backtoschool", 2), ("first day of school", 2), ("first school day", 2)],
    "badminton": [("badminton", 2)],
    "baseball": [("baseball", 2)],
    "basketball": [("basketball", 2)],
    "bbq": [("barbecue", 2), ("barbeque", 2), ("bbq", 2), ("cookout", 2), ("grill", 2), ("grilling", 2)],
    "beer": [("beer", 2), ("beers", 2), ("brewery", 2), ("pub", 2)],
    "birthday": [("bday", 2), ("bday party", 2), ("birthday", 2), ("birthday party", 2), ("birthdays", 2)],
    "book-club": [("book club", 2), ("book group", 2), ("reading", 2)],
    "bowling": [("bowling", 2)],
    "breakfast": [("breakfast", 2), ("breakfasts", 2), ("brunch", 2), ("brunches", 2)],
    "camping": [("camp", 2), ("camping", 2), ("campsite", 2)],
    "chinese-new-year": [("chinese lunar new year", 4), ("chinese new year", 4), ("chinese new year's", 4), ("chinese new years", 4), ("vietnamese new year", 4)],
    "cinema": [("cinema", 2), ("film", 2), ("films", 2), ("movie", 2), ("movie night", 2), ("movies", 2), ("visiting cinema", 2), ("watching a movie", 2)],
    "clean": [("chores", 2), ("clean house", 2), ("clean the apartment", 2), ("clean the house", 2), ("cleaning", 2), ("housecleaning", 2), ("tidy up", 2), ("vacuum clean", 2), ("vacuum cleaning", 2)],
    "climbing": [("bouldering", 2), ("climbing", 2), ("indoor climbing", 2), ("rock climbing", 2)],
    "code": [("code review", 2), ("coding", 2), ("hackathon", 2), ("learn to code", 2), ("programming", 2), ("software dev", 2), ("write code", 2)],
    "coffee": [("cafe", 2), ("coffee", 2), ("coffees", 2), ("espresso", 2)],
    "concert": [("concert", 2), ("concerts", 2), ("gig", 2), ("gigs", 2)],
    "cooking": [("cook dinner", 3), ("cook lunch", 3), ("cook meal", 3), ("cooking", 3), ("make dinner", 3), ("make lunch", 3), ("prepare dinner", 3), ("prepare lunch", 3), ("prepare meal", 3)],
    "cricket": [("cricket competition", 2), ("cricket game", 2), ("cricket match", 2)],
    "cycling": [("bicycle", 2), ("bicycles", 2), ("bike", 2), ("bikes", 2), ("biking", 2), ("cycling", 2), ("mountain bike", 2), ("mountain biking", 2)],
    "cycling-bmx": [("bmx", 2)],
    "dancing": [("dance", 2), ("dances", 2), ("dancing", 2)],
    "date-night": [("candle light dinner", 3), ("candlelight dinner", 3), ("date night", 2), ("romantic dinner", 3)],
    "dentist": [("dental", 2), ("dental appointment", 2), ("dental checkup", 2), ("dentist", 2), ("dentistry", 2), ("teeth cleaning", 3)],
    "dinner": [("dinner", 2), ("dinners", 2)],
    "drinks": [("bachelorette party", 2), ("cocktail", 2), ("cocktails", 2), ("drinks", 2), ("happy hour", 2), ("night out", 2), ("stag party", 2)],
    "field-hockey": [("field hockey", 2)],
    "game-night": [("board game", 2), ("board games", 2), ("boardgame", 2), ("boardgames", 2), ("games night", 2)],
    "generic-new-year": [("new year", 3), ("new year's", 3), ("new years", 3)],
    "golf": [("golf", 2), ("golf course", 2), ("golfing", 2)],
    "graduation": [("commencement", 2), ("graduation", 2), ("graduation ceremony", 2)],
    "gym": [("crossfit", 2), ("fitness center", 2), ("fitness class", 2), ("fitness evaluation", 2), ("fitness program", 2), ("fitness test", 2), ("fitness training", 2), ("gym", 2), ("weight lifting", 2), ("weightlifting", 2), ("workout", 2), ("workouts", 2)],
    "haircut": [("barber", 2), ("hair", 2), ("hair appointment", 2), ("haircut", 2), ("hairdresser", 2), ("salon appointment", 2)],
    "halloween": [("all hallows eve", 2), ("all saints eve", 2), ("allhalloween", 2), ("halloween", 2), ("halloween dance", 2), ("helloween", 2)],
    "hiking": [("hike", 2), ("hikes", 2), ("hiking", 2)],
    "islamic-new-year": [("hijri new year", 4), ("islamic new year", 4), ("parsi new year", 4)],
    "karate": [("aikido", 2), ("jiu jitsu", 2), ("jiu-jitsu", 2), ("judo", 2), ("jujutsu", 2), ("karate", 2), ("martial arts", 2), ("taekwondo", 2)],
    "kayaking": [("canoe", 2), ("canoeing", 2), ("kayaking", 2)],
    "learn-instrument": [("band practice", 2), ("cello", 2), ("choir", 2), ("choir practice", 2), ("clarinet", 2), ("classical music", 2), ("contrabass", 2), ("cornett", 2), ("flute", 2), ("guitar lesson", 2), ("music class", 2), ("music ensemble", 2), ("music lesson", 2), ("oboe", 2), ("orchestra", 2), ("piano", 2), ("saxophone", 2), ("singing", 2), ("string quartett", 2), ("trombone", 2), ("trumpet", 2), ("tuba", 2)],
    "learn-language": [("english class", 2), ("english course", 2), ("french class", 2), ("french course", 2), ("german class", 2), ("german course", 2), ("italian class", 2), ("language class", 2), ("practice english", 2), ("practice french", 2), ("practice german", 2), ("spanish class", 2)],
    "lunch": [("lunch", 2), ("luncheon", 2), ("lunches", 2)],
    "mardi-gras": [("fat tuesday", 2), ("mardi gras", 2), ("mardigras", 2), ("shrove tuesday", 2)],
    "massage": [("back rub", 2), ("backrub", 2), ("massage", 2), ("massages", 2), ("spa", 2)],
    "nowruz": [("nowruz", 4), ("persian new year", 4)],
    "ping-pong": [("ping pong", 2), ("ping-pong", 2), ("pingpong", 2), ("table tennis", 4)],
    "plan-my-day": [("plan day", 2), ("plan quarter", 2), ("plan vacation", 2), ("plan week", 2), ("vacation planning", 2), ("week planning", 2)],
    "pride": [("christopher street day", 2), ("dyke march", 2), ("euro pride", 2), ("europride", 2), ("gay and lesbian", 2), ("gay lesbian", 2), ("gay parade", 2), ("gay pride", 2), ("gaygler", 2), ("gayglers", 2), ("lesbian march", 2), ("lesbian parade", 2), ("lesbian pride", 2), ("world pride", 2), ("worldpride", 2)],
    "reach-out": [("reach out to", 2), ("write letter", 2)],
    "read": [("book", 2), ("ebook", 2), ("reading", 2), ("reading time", 2)],
    "repair": [("diy", 2), ("electrician", 2), ("fix", 2), ("fridge repair", 2), ("handyman", 2), ("home repair", 2), ("maintenance", 2), ("plumber", 2)],
    "rhythmic-gymnastics": [("rhythmic gymnastics", 2)],
    "rowing": [("head of the charles", 2), ("head of the river race", 2), ("may bumps", 2), ("rowing", 2)],
    "rugby-sevens": [("rugby", 2)],
    "running": [("jog", 2), ("jogging", 2), ("jogs", 2), ("running", 2), ("sprinting", 2), ("track and field", 2)],
    "saint-patricks-day": [("saint patricks day", 2), ("st patricks", 2), ("st. patrick's day", 2)],
    "santa": [("father christmas", 4), ("meet santa", 2), ("santa claus", 2), ("visit santa", 2)],
    "skiing": [("ski", 2), ("skiing", 2), ("skis", 2)],
    "sleep": [("nap", 2), ("napping", 2), ("relaxing", 2), ("resting", 2), ("sleep", 2), ("sleeping", 2)],
    "soccer": [("soccer", 2)],
    "swimming": [("diving", 2), ("swim", 2), ("swimming", 2), ("swims", 2), ("synchronized swimming", 2)],
    "tennis": [("tennis", 2)],
    "thanksgiving": [("thanksgiving", 2)],
    "triathlon": [("triathlon", 2)],
    "valentines-day": [("valentine day", 2), ("valentine's day", 2), ("valentines day", 2)],
    "video-gaming": [("agdq", 3), ("games done quick", 3), ("sgdq", 3), ("video game", 2), ("video games", 2), ("video gaming", 2), ("videogames", 2), ("videogaming", 2)],
    "volleyball": [("volleyball", 2)],
    "walk": [("going for a walk", 2), ("walking", 2)],
    "walking-dog": [("dog sitting", 2), ("dog walker", 2), ("dog walking", 2), ("dogsitting", 2), ("take dog out", 2), ("take out dog", 2), ("walk dog", 2), ("walk the dog", 2)],
    "wedding": [("wedding", 2), ("wedding eve", 2), ("wedding-eve party", 2), ("weddings", 2)],
    "christmas": [("christmas", 3), ("x-mas", 3), ("xmas", 3)],
    "christmas-meal": [("christmas brunch", 5), ("christmas dinner", 5), ("christmas eve brunch", 5), ("christmas eve dinner", 5), ("christmas eve lunch", 5), ("christmas eve luncheon", 5), ("christmas lunch", 5), ("christmas luncheon", 5), ("x-mas brunch", 5), ("x-mas dinner", 5), ("x-mas eve brunch", 5), ("x-mas eve dinner", 5), ("x-mas eve lunch", 5), ("x-mas eve luncheon", 5), ("x-mas lunch", 5), ("x-mas luncheon", 5), ("xmas brunch", 5), ("xmas dinner", 5), ("xmas eve brunch", 5), ("xmas eve dinner", 5), ("xmas eve lunch", 5), ("xmas eve luncheon", 5), ("xmas lunch", 5), ("xmas luncheon", 5)],
    "christmas-party": [("christmas eve party", 4), ("christmas party", 4), ("x-mas eve party", 4), ("x-mas party", 4), ("xmas eve party", 4), ("xmas party", 4)],
    "yoga": [("yoga", 2)],

    # 2026-09-29 additions -- see this file's own header docstring for
    # the full reasoning behind each group below.
    "bills": [("bill", 2), ("bills", 2), ("pay bill", 2), ("pay bills", 2), ("utility bill", 2), ("utilities", 2)],
    "bus": [("bus", 2), ("bus ride", 2)],
    "delivery": [("delivery", 2), ("parcel", 2), ("parcel pick-up", 2), ("parcel pickup", 2), ("package delivery", 2)],
    "doctor": [("doctor", 2), ("doctor's appointment", 2), ("doctors appointment", 2), ("gp appointment", 2)],
    "flight": [("flight", 2), ("flights", 2), ("catch a flight", 2), ("board a flight", 2)],
    "hotel": [("hotel", 2), ("hotel booking", 2), ("hotel check-in", 2), ("check into hotel", 2)],
    "interview": [("interview", 2), ("job interview", 2), ("interviewing", 2)],
    "kids-pickup-dropoff": [("school pickup", 2), ("school pick-up", 2), ("school dropoff", 2), ("school drop-off", 2), ("pick up kids", 2), ("pick up the kids", 2), ("drop off kids", 2), ("drop off the kids", 2)],
    "online-classes": [("online class", 2), ("online classes", 2), ("online course", 2), ("virtual class", 2), ("zoom class", 2)],
    "party": [("party", 2), ("parties", 2), ("house party", 2)],
    "photography": [("photography", 2), ("photo shoot", 2), ("photoshoot", 2), ("photography session", 2)],
    "restaurant": [("restaurant", 2), ("restaurants", 2), ("table reservation", 2), ("book a table", 2), ("fine dining", 2)],
    "shopping": [("shopping", 2), ("go shopping", 2), ("grocery shopping", 2)],
    "studying": [("studying", 2), ("study session", 2), ("exam prep", 2), ("homework", 2)],
    "trip": [("trip", 2), ("travel", 2), ("travelling", 2), ("traveling", 2), ("road trip", 2)],
    "tv": [("tv", 2), ("watch tv", 2), ("television", 2), ("binge watch", 2), ("binge-watch", 2)],
    "video-call": [("video call", 2), ("video call with", 2), ("video chat", 2), ("zoom call", 2)],
    "vote": [("vote", 2), ("voting", 2), ("election day", 2), ("go vote", 2)],
    # Generic fallback beneath the two specific disciplines above --
    # "artistic gymnastics"/"rhythmic gymnastics" are both longer AND
    # lower-priority than plain "gymnastics", so match_flair's own
    # tie-break (longer keyword wins at equal priority, and priority 2
    # beats 5 regardless) always prefers them when a name is specific.
    "gymnastics-generic": [("gymnastics", 5)],
    # Scenery/color backgrounds and calendar-grid entries -- priority 5
    # throughout, see the header docstring's false-positive note.
    "university": [("university", 5), ("college", 5), ("campus", 5)],
    "museum": [("museum", 5), ("art gallery", 5), ("gallery", 5)],
    "debate": [("debate", 5), ("debate club", 5), ("debate practice", 5)],
    "mountain": [("mountain", 5), ("mountains", 5)],
    "sea": [("sea", 5), ("seaside", 5), ("beach", 5), ("ocean", 5)],
    "sky": [("sky", 5)],
    "wood": [("wood", 5), ("woods", 5), ("forest", 5), ("woodworking", 5)],
    "blue": [("blue", 5)],
}


SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# Set once, at app startup (main.py's lifespan calls `configure` with
# `Settings.flairs_dir`) -- module-level rather than threaded through
# every db.py call site that eventually needs it (banner_for_object,
# effective_page_banner, ... -- a dozen-plus routers deep) because db.py
# is deliberately `conn`-only everywhere else, never `Settings`-aware;
# see this module's own docstring for why the directory itself has to be
# operator-configurable in the first place. None (never configured, e.g.
# a test that forgot to call it) makes `flair_image_url` always return
# None -- a missing config is "no flairs available," not a crash.
_flairs_dir: Path | None = None


def configure(directory: Path | None) -> None:
    """Called once from main.py's lifespan (and freely from tests, which
    each get their own tmp_path) -- points this module at wherever the
    operator's actual photo files live. `None` resets to "not configured"
    (tests use this in teardown so one test's directory can never leak
    into another's)."""
    global _flairs_dir
    _flairs_dir = directory


def get_flairs_dir() -> Path | None:
    """The directory `configure` last pointed this module at, or None.
    routers/flairs.py's own serving route reads this directly (not
    `request.app.state.settings.flairs_dir`) so there's exactly one
    source of truth for "where do the photos live" -- the same one
    `flair_image_url` below already uses to decide whether a URL exists
    at all in the first place."""
    return _flairs_dir


def flair_image_url(flair_id: str) -> str | None:
    """The URL to actually show for `flair_id`, or None when no matching
    file exists under the configured `flairs_dir` (never configured at
    all, the directory doesn't exist yet, or this specific id's file was
    never placed there) -- callers (db.py's `effective_page_banner`/
    `banner_for_object`) treat None exactly like `match_flair` itself
    returning no match, falling through to the next tier.

    Checks `{flairs_dir}/{flair_id}{ext}` for each of `SUPPORTED_
    EXTENSIONS` in turn (first one found wins) -- an operator can supply
    a JPEG, PNG, or WEBP under the documented id, whichever they have on
    hand, without needing to convert it to match some one fixed
    extension. Served through `GET /flairs/{flair_id}` (routers/
    flairs.py), not the app's own `/static/` mount -- these bytes never
    live inside the installed app tree at all. Cache-busted by the file's
    own mtime (same idea as deps.py's `static_url`, reimplemented here
    rather than imported -- see that function's own note on why this
    module can't import deps.py without a real circular import)."""
    if _flairs_dir is None:
        return None
    for ext in SUPPORTED_EXTENSIONS:
        path = _flairs_dir / f"{flair_id}{ext}"
        try:
            version = int(path.stat().st_mtime)
        except OSError:
            continue
        return f"/flairs/{flair_id}?v={version}"
    return None


def match_flair(name: str | None) -> str | None:
    """The flair (if any) whose keyword list best matches `name` -- a
    task/event/habit-task's own title, or a label/group/project's own
    name. Case-insensitive substring match (a keyword phrase anywhere in
    the name counts, not just a whole-word/whole-name match -- "Weekly
    yoga class" matches "yoga" the same as a name that's just "Yoga").
    Ties (a name matching keywords from more than one flair) break on the
    lower `priority` number winning -- confirmed via AskUserQuestion as
    the tie-break rule, using the reference data's own confidence
    ranking rather than e.g. preferring whichever matched phrase is
    longest. A further tie (same priority, more than one flair) breaks on
    the longest matching keyword phrase, then alphabetically by flair id
    -- both deterministic, neither was asked about since a same-priority
    collision is rare enough in practice not to be a real product
    decision either way.

    Deliberately independent of whether `flair_image_url` would actually
    find a file for the winning id -- this is pure keyword matching over
    the full DATA table regardless of which photos an operator has
    gotten around to supplying yet; callers are the ones that fall
    through to "no banner" when the matched id has no file configured."""
    if not name:
        return None
    lowered = name.lower()
    best: tuple[int, int, str, str] | None = None  # (priority, -len(kw), kw, flair_id)
    for flair_id, keywords in FLAIR_KEYWORDS.items():
        for keyword, priority in keywords:
            if keyword in lowered:
                candidate = (priority, -len(keyword), keyword, flair_id)
                if best is None or candidate < best:
                    best = candidate
    return best[3] if best else None
