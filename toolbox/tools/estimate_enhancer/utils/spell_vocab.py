# Construction, roofing, siding, and framing vocabulary for spell checking.
# These words are seeded into the pyspellchecker dictionary to reduce
# false positives on trade-specific terminology.

_CONSTRUCTION_WORDS = {
    # -- Materials --
    'shingle', 'shingles', 'asphalt', 'membrane', 'underlayment', 'underlay',
    'drip', 'edge', 'flashing', 'counterflashing', 'fascia', 'soffit',
    'truss', 'trusses', 'rafter', 'rafters', 'joist', 'joists', 'stud', 'studs',
    'beam', 'beams', 'header', 'headers', 'sill', 'plate', 'sheathing', 'plywood',
    'osb', 'drywall', 'gypsum', 'insulation', 'batt', 'fiberglass', 'cellulose',
    'spray', 'foam', 'caulk', 'sealant', 'adhesive', 'fastener', 'nail', 'screw',
    'bolt', 'anchor', 'clip', 'hanger', 'strap', 'bracket',

    # -- Roofing --
    'ridge', 'hip', 'valley', 'eave', 'eaves', 'rake', 'gable', 'dormer',
    'cricket', 'saddle', 'vent', 'vents', 'turbine', 'louver', 'louvers',
    'tile', 'tiles', 'slate', 'tpo', 'epdm', 'bitumen', 'modified', 'gravel',
    'capsheet', 'basesheet', 'builtup', 'rubber', 'membrane', 'hip', 'valley',
    'ridges', 'valleys', 'crickets', 'flashings', 'underlayments',

    # -- Siding / Exterior --
    'vinyl', 'aluminum', 'cement', 'hardie', 'batten', 'clapboard', 'shake',
    'shakes', 'lap', 'dutch', 'panel', 'panels', 'trim', 'corner', 'post',
    'channel', 'starter', 'frieze', 'band', 'wainscot', 'skirt',
    'siding', 'sider',

    # -- Framing / Structural --
    'jack', 'king', 'cripple', 'lintel', 'girder', 'joist', 'rafter', 'collar',
    'tie', 'ties', 'web', 'chord', 'bottom', 'top', 'sole', 'mud', 'rim', 'band',
    'ledger', 'girt', 'purlin', 'strut', 'brace', 'bracing', 'blocking',
    'fireblock', 'bridging', 'shearwall', 'braced', 'diaphragm', 'subfloor',
    'backer', 'denshield', 'hardibacker', 'wonderboard', 'ditra',
    'framing', 'framer', 'frame', 'framed',
    'stud', 'studs', 'header', 'headers', 'beam', 'beams',
    'joist', 'joists', 'truss', 'trusses', 'rafter', 'rafters',
    'sheathing', 'plywoods', 'subfloor', 'subflooring',

    # -- Foundations / Concrete --
    'footing', 'foundation', 'slab', 'stem', 'crawl', 'basement', 'grade',
    'monolithic', 'floating', 'frost', 'bearing', 'nonbearing', 'retaining',
    'pier', 'column', 'piling', 'caisson', 'mat', 'raft', 'pad', 'spread',
    'pile', 'cap', 'gradebeam', 'tiedown', 'holddown',
    'concrete', 'mortar', 'rebar', 'reinforcing', 'cmu', 'block', 'brick',
    'stone', 'veneer', 'stucco', 'efis', 'eifs', 'lathe', 'scratch',
    'float', 'trowel', 'screed', 'bullnose', 'cove', 'coping', 'copingstone',
    'masonry',

    # -- HVAC / Plumbing / Electrical --
    'ductwork', 'register', 'grille', 'diffuser', 'condensate', 'refrigerant',
    'copper', 'pvc', 'abs', 'pex', 'conduit', 'romex', 'junction', 'breaker',
    'gfci', 'afci',

    # -- Waterproofing / Drainage --
    'waterproofing', 'dampproofing', 'vapor', 'barrier', 'airbarrier',
    'sealing', 'weatherization', 'expansion', 'control', 'joint',
    'caulking', 'sealants',
    'gutters', 'downspouts', 'gutter', 'downspout', 'leader', 'conductor',
    'head', 'scupper', 'overflow', 'drainage', 'swale', 'bioswale', 'cistern',
    'rainwater', 'stormwater', 'runoff', 'detention', 'retention', 'pond',
    'permeable', 'porous', 'paver', 'interlocking', 'geotextile', 'drain',
    'frenchdrain', 'perforated', 'sock', 'gravel', 'crushed', 'stone', 'riprap',
    'rubble', 'excavation', 'trenching', 'dewatering', 'backfill', 'compaction',

    # -- Exterior Details --
    'lattice', 'pergola', 'arbor', 'trellis', 'deck', 'porch', 'patio', 'stoop',
    'landing', 'tread', 'riser', 'stringer', 'nosing', 'baluster', 'railing',
    'handrail', 'newel', 'picket', 'post', 'balcony', 'parapet', 'awning',
    'canopy', 'marquee',

    # -- Doors / Windows / Trim --
    'casement', 'awning', 'doublehung', 'singlehung', 'slider', 'sliding',
    'picture', 'fixed', 'transom', 'sidelight', 'skylight', 'roofwindow',
    'tubular', 'daylight', 'doorway', 'threshold', 'jamb', 'casing',
    'molding', 'baseboard', 'base', 'shoe', 'quarter', 'round', 'cove',
    'crown', 'cornice', 'dentil', 'reveal', 'plaster', 'lath',
    'stucco', 'render', 'parging', 'browncoat', 'scratchcoat',
    'finishcoat', 'skimcoat',

    # -- Verbs / Adjectives --
    'install', 'repair', 'replace', 'remove', 'demolish', 'construct', 'build',
    'sheath', 'wrap', 'flash', 'seal', 'paint', 'stain', 'prime', 'coat',
    'finish', 'align', 'level', 'plumb', 'square', 'secure', 'attach', 'connect',
    'join', 'splice', 'lap', 'butt', 'miter', 'bevel', 'chamfer',
    'existing', 'new', 'damaged', 'deteriorated', 'rotted', 'corroded', 'missing',
    'detached', 'loose', 'warped', 'cracked', 'broken', 'leaking', 'exposed',
    'concealed', 'rough', 'finished',
    'splice', 'spliced', 'splicing', 'lapped', 'lapping', 'butted', 'butting',
    'mitered', 'mitering', 'beveled', 'beveling', 'chamfered', 'chamfering',
    'aligned', 'aligning', 'leveled', 'leveling', 'plumbed', 'plumbing',
    'squared', 'squaring', 'secured', 'securing', 'attached', 'attaching',
    'connected', 'connecting', 'joined', 'joining', 'sealed', 'sealing',
    'flashed', 'flashing', 'wrapped', 'wrapping', 'sheathed', 'sheathing',
    'framed', 'framing', 'constructed', 'constructing', 'installed', 'installing',
    'repaired', 'repairing', 'replaced', 'replacing', 'removed', 'removing',
    'demolished', 'demolishing', 'painted', 'painting', 'stained', 'staining',
    'primed', 'priming', 'coated', 'coating', 'finished', 'finishing',
    'caulked', 'caulking',

    # -- Trades / Roles --
    'carpentry', 'roofing', 'siding', 'drywalling', 'taping', 'mudding',
    'spackling', 'texturing', 'sanding', 'priming', 'painting', 'staining',
    'varnishing', 'polyurethaning', 'epoxy', 'sealer',
    'caulker', 'roofer', 'sider', 'framer', 'carpenter', 'drywaller', 'painter',
    'contractor', 'subcontractor', 'builder', 'remodeler', 'renovator',
    'restorer', 'mitigation', 'abatement', 'remediation', 'reconstruction',
    'addition', 'alteration', 'improvement', 'buildout', 'fitout',
    'demolition', 'excavation', 'grading', 'landscaping', 'hardscaping',

    # -- Common compounds / plurals --
    'dripedge', 'fascias', 'soffits', 'gables', 'dormers', 'ridges', 'valleys',
    'flashings', 'underlayments', 'joists', 'studs', 'headers', 'beams',
    'rafters', 'trusses', 'sheathings', 'plywoods', 'drywalls',
    'insulations', 'sealants', 'adhesives', 'fasteners', 'clips', 'hangers',
    'straps', 'brackets', 'anchors', 'bolts', 'screws', 'nails',
    'gutters', 'downspouts', 'vents', 'louvers', 'panels', 'shakes',
    'crickets', 'saddles', 'footings', 'foundations', 'slabs', 'basements',
    'crawls', 'columns', 'piers', 'caps', 'ledgers', 'purlins', 'struts',
    'braces', 'bridgings', 'blockings', 'ties', 'webs', 'chords',
    'lintels', 'girders', 'sills', 'plates', 'mud', 'soles', 'rims', 'bands',

    # -- Proper names / Locations encountered in documents --
    'baney', 'rockton', 'bolingbrook', 'esposito', 'summerset',

    # -- Brands --
    'certainteed', 'itel',

    # -- Abbreviations --
    'med', 'approx', 'cond', 'tel', 'sqft', 'sqs',

    # -- Equipment / Trade terms --
    'telehandler', 'modbit', 'housewrap', 'repairability',

    # -- Estimate document terms --
    # 'pre' covers hyphenated compounds like 'Pre-existing' (checked as parts)
    'pre', 'xactimate', 'screenshot', 'screenshots',
}
