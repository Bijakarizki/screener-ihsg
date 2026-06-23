"""
Konfigurasi screener saham IHSG.
Parameter di sini SAMA PERSIS dengan notebook screener_v2_updated.ipynb
(Setup 1, Setup 2, Setup 3 -- daily only, tanpa intraday 1m).
"""

# ============================================================
# DAFTAR TICKER IHSG (931 saham unik, dari notebook asli)
# ============================================================
SAHAM_IHSG = [
    'BRPT', 'TPIA', 'BREN', 'CUAN', 'PTRO', 'SULI', 'MCOL', 'CDIA',
    'RAJA', 'RATU', 'SINI', 'CBRE', 'MINA', 'PSKT', 'PADI', 'BUVA',
    'UANG', 'ARCI', 'FORU', 'CITA', 'SUGI', 'BRMS', 'ENRG', 'BUMI',
    'VKTR', 'DEWA', 'MDLN', 'MDIA', 'VIVA', 'INDF', 'ICBP', 'LSIP',
    'SIMP', 'ROTI', 'META', 'DNET', 'BACA', 'AMMN', 'NFCX', 'MCAS',
    'CASA', 'INKP', 'TKIM', 'BSDE', 'SMMA', 'DSSA', 'BSIM', 'DUTI',
    'DMAS', 'KIJA', 'MLPT', 'SILO', 'LPCK', 'MPPA', 'NOBU', 'LINK',
    'MNCN', 'BMTR', 'MSKY', 'KPIG', 'IPTV', 'MSIN', 'BCAP', 'BHIT',
    'BABP', 'IATA', 'ASII', 'UNTR', 'AUTO', 'SMSM', 'ACST', 'AALI',
    'MMLP', 'MEGA', 'BBHI', 'ALLO', 'GARU', 'PNBN', 'PNLF', 'PNIN',
    'PANS', 'CFIN', 'AMAG', 'VRNA', 'BBCA', 'DCII', 'MORA', 'WIFI',
    'WIRG', 'AADI', 'COIN', 'FILM', 'NETV', 'BBRI', 'BMRI', 'BBNI',
    'BBTN', 'BRIS', 'BNGA', 'NISP', 'BJBR', 'BJTM', 'ARTO', 'BBYB',
    'BDMN', 'BTPN', 'SDRA', 'AGRO', 'AMAR', 'BBKP', 'BKSW', 'BNBA',
    'BNII', 'BNLI', 'MAYA', 'MCOR', 'PNBS', 'BGTG', 'BMAS', 'BBMD',
    'BSWD', 'BCIC', 'BPII', 'BANK', 'BHAT', 'AGRS', 'DNAR', 'INPC',
    'BVIC', 'SUPA', 'YOII', 'ADRO', 'PTBA', 'ITMG', 'HRUM', 'PGAS',
    'MEDC', 'AKRA', 'MBMA', 'INCO', 'ANTM', 'MDKA', 'NCKL', 'TINS',
    'ELSA', 'ADMR', 'INDY', 'KKGI', 'GEMS', 'DOID', 'BSSR', 'MBAP',
    'TOBA', 'SMMT', 'BYAN', 'GTBO', 'ARII', 'CNKO', 'DKFT', 'DSSP',
    'KOPI', 'BOSS', 'SGER', 'WINS', 'LEAD', 'ESSA', 'PEDO', 'SMRU',
    'FIRE', 'MBSS', 'PKPK', 'PTIS', 'BNBR', 'BIPI', 'RUIS', 'LAPD',
    'MTFN', 'SQMI', 'APEX', 'MPXL', 'SMCB', 'ZINC', 'PSAB', 'ARTI',
    'MITI', 'CTTH', 'TARA', 'EMAS', 'HGII', 'MINE', 'DGWG', 'UNVR',
    'MYOR', 'GGRM', 'HMSP', 'WIIM', 'SIDO', 'CPIN', 'JPFA', 'MAIN',
    'CLEO', 'CMRY', 'ULTJ', 'KINO', 'GOOD', 'CAMP', 'AMRT', 'MIDI',
    'ACES', 'MAPI', 'MAPA', 'RALS', 'ERAA', 'EPMT', 'DAYA', 'HERO',
    'MLBI', 'DLTA', 'STTP', 'CEKA', 'TBLA', 'PSDN', 'SKLT', 'RICY',
    'WOOD', 'SCNP', 'COCO', 'PGUN', 'WMUU', 'KEJU', 'ALTA', 'CSAP',
    'TRIO', 'TGKA', 'KBLI', 'LPPF', 'MPMX', 'FOOD', 'AISA', 'BISI',
    'BTEK', 'DMND', 'HOKI', 'IIKP', 'ISSP', 'KDSI', 'MGNA', 'MRAT',
    'MTDL', 'NASI', 'PCAR', 'SKBM', 'TBMS', 'TCID', 'TSPC', 'UNIC',
    'YUPI', 'FORE', 'BRRC', 'BEEF', 'RLCO', 'TLKM', 'ISAT', 'EXCL',
    'MTEL', 'TOWR', 'TBIG', 'EMTK', 'SCMA', 'BUKA', 'BELI', 'DMMX',
    'TFAS', 'DIVA', 'KREN', 'SRTG', 'PGJO', 'TECH', 'AWAN', 'GOTO',
    'EDGE', 'AXIO', 'KIOS', 'SWAT', 'HEAL', 'SOTS', 'BAYU', 'LUCK',
    'SMGR', 'INTP', 'CMBP', 'JSMR', 'CMNP', 'ADHI', 'PTPP', 'WIKA',
    'WEGE', 'WTON', 'TOTL', 'NRCA', 'PPRE', 'WSKT', 'IDPR', 'NELY',
    'TPMA', 'RIGS', 'HUMP', 'TCPI', 'WSBP', 'PBSA', 'DGIK', 'MTRA',
    'RBMS', 'SSIA', 'TOPS', 'UCON', 'BTON', 'KRAS', 'LION', 'NIKL',
    'PICO', 'GDST', 'CBDK', 'CTRA', 'PWON', 'SMRA', 'ASRI', 'DILD',
    'JRPT', 'MKPI', 'APLN', 'PLIN', 'RODA', 'BEST', 'FMII', 'CITY',
    'GWSA', 'OMRE', 'MTSM', 'LPKR', 'KOTA', 'LAND', 'POLI', 'BIKA',
    'FORZ', 'URBN', 'MPRO', 'NIRO', 'BCIP', 'BKSL', 'COWL', 'DART',
    'EMDE', 'GAMA', 'GPRA', 'INDO', 'JSPT', 'MTLA', 'MYRX', 'PAMG',
    'PJAA', 'PPRO', 'RDTX', 'RISE', 'ROCK', 'SCBD', 'SMDM', 'TRIN',
    'MORE', 'PUDP', 'KSIX', 'KLBF', 'MIKA', 'PRDA', 'KADF', 'INAF',
    'PEHA', 'CARE', 'SOHO', 'SAME', 'OMED', 'BMHS', 'DGNS', 'RSGK',
    'IRRA', 'DVLA', 'KMDS', 'MEDI', 'PHAM', 'PYFA', 'WARD', 'HDTX',
    'MBTO', 'MERK', 'SQBB', 'CHEK', 'DKHH', 'MDLA', 'OBAT', 'AGII',
    'AVIA', 'MARK', 'INRU', 'DPNS', 'IGAR', 'BRNA', 'FPNI', 'MDKI',
    'TRST', 'AKPI', 'YPAS', 'JKSW', 'ALMI', 'BAJA', 'AMFG', 'ARNA',
    'EKAD', 'FASW', 'IMPC', 'INAI', 'INCI', 'IPOL', 'LMSH', 'MLIA',
    'PBID', 'SIAP', 'SRSN', 'TALF', 'TOTO', 'VOKS', 'ASPR', 'TMAS',
    'SMDR', 'BIRD', 'ASSA', 'IPCM', 'ELPI', 'CARS', 'TRJA', 'BPTR',
    'HAIS', 'KJEN', 'TNCA', 'WEHA', 'CMPP', 'MIRA', 'DEAL', 'GIAA',
    'HATM', 'HITS', 'INDX', 'JAYA', 'LRNA', 'PORT', 'SAFE', 'SDMU',
    'SHIP', 'TAXI', 'PSSI', 'LAJU', 'PSAT', 'BLOG', 'PJHB', 'WBSA',
    'SSMS', 'STAA', 'DSNG', 'TAPG', 'BWPT', 'CSRA', 'FAPA', 'GZCO',
    'JAWA', 'MAGP', 'PALM', 'SMAR', 'SGRO', 'ANJT', 'CPRO', 'DNSG',
    'FLEX', 'UNSP', 'ADMG', 'ARGO', 'CNTX', 'ERTX', 'ESTI', 'INDR',
    'MYTX', 'PBRX', 'POLY', 'SRIL', 'SSTM', 'TRIS', 'UNIT', 'VSTI',
    'MERI', 'PMUI', 'KAQI', 'AGAR', 'AKKU', 'ALKA', 'ALTO', 'APII',
    'ARMY', 'ATPK', 'AYTL', 'BIMA', 'BINO', 'BLTZ', 'BMSR', 'CANI',
    'CICO', 'CLAY', 'CLPI', 'CMNT', 'DEPO', 'DYAN', 'ETWA', 'FREN',
    'GARE', 'GLOB', 'GMFI', 'HADE', 'HDFA', 'HELI', 'HILL', 'HOTL',
    'IMJS', 'INDS', 'INTD', 'IRSX', 'JGLE', 'KBLM', 'KBRI', 'KEEN',
    'KMTR', 'LCGP', 'LMAS', 'MABA', 'MAMI', 'MARI', 'MASA', 'MFIN',
    'MOCH', 'MREI', 'MTWI', 'OCAP', 'OILS', 'PDES', 'PEGE', 'PETS',
    'PGLI', 'PNSE', 'PPGL', 'PSGO', 'PTSP', 'RELI', 'RIMO', 'SURI',
    'TELE', 'TIRA', 'TMPO', 'TRIM', 'VICO', 'VINS', 'WAPO', 'WICO',
    'ZBRA', 'ABDA', 'ABMM', 'ADMF', 'AHAP', 'AMOR', 'ASBI', 'ASDM',
    'ASJT', 'ASMI', 'ASRM', 'BBLD', 'BBSI', 'BFIN', 'BPFI', 'DEFI',
    'FUJI', 'GSMF', 'JMAS', 'LIFE', 'LPGI', 'MASB', 'MFMI', 'POLA',
    'POOL', 'SFAN', 'TIFA', 'TRUS', 'TUGU', 'WOMF', 'YULE', 'ADES',
    'ASGR', 'BATA', 'BOLT', 'BUAH', 'BUDI', 'CASS', 'CINT', 'CSMI',
    'DUCK', 'EAST', 'ENAK', 'FAST', 'FISH', 'FOLK', 'GDYR', 'GEMA',
    'GJTL', 'HRTA', 'IMAS', 'JECC', 'KAEF', 'KOBX', 'LTLS', 'MAPB',
    'MDRN', 'MICE', 'MUTU', 'MYOH', 'PZZA', 'RAAM', 'RANC', 'SCCO',
    'SCPI', 'SDPC', 'SIPD', 'SONA', 'SOSS', 'SPMA', 'TAMA', 'TGUK',
    'UCID', 'VICI', 'VTNY', 'ABBA', 'ACRO', 'AREA', 'ATIC', 'ATLA',
    'CASH', 'CENT', 'CHIP', 'CYBR', 'DATA', 'DIGI', 'DOOH', 'DOSS',
    'ELIT', 'GHON', 'GOLD', 'HDIT', 'IBST', 'ICON', 'IDEA', 'INET',
    'INOV', 'IOTF', 'ISAP', 'JAST', 'JATI', 'JTPE', 'KETR', 'KLIN',
    'LCKM', 'MKNT', 'MSTI', 'NANO', 'NAIK', 'NINE', 'RUNS', 'SEMA',
    'SKYB', 'SLIS', 'TOSK', 'TRON', 'UVCR', 'VAST', 'VISI', 'WGSH',
    'YELO', 'ZYRX', 'ADCP', 'BEBS', 'BDKR', 'BUKK', 'CGAS', 'COAL',
    'DAAZ', 'DRMA', 'DWGL', 'FUTR', 'GGRP', 'ITMA', 'JKON', 'JSKY',
    'KKES', 'LABA', 'MKAP', 'MPOW', 'NICE', 'NICL', 'NPGF', 'OASA',
    'PGEO', 'POWR', 'RMKE', 'SOCI', 'SOLA', 'SURE', 'TEBE', 'TGRA',
    'TOOL', 'TOYS', 'TRGU', 'TRUE', 'WOWS', 'ATAP', 'BALI', 'BAPA',
    'BAPI', 'BKDP', 'CPRI', 'DFAM', 'DADA', 'ECII', 'GPSO', 'GRIA',
    'GRPH', 'GRPM', 'GTRA', 'HOME', 'HOMI', 'HOPE', 'HRME', 'INPP',
    'IPAC', 'IPCC', 'JIHD', 'KDTN', 'LPIN', 'LPLI', 'LPPS', 'LUCY',
    'MANG', 'MKTR', 'NASA', 'NZIA', 'PACK', 'PANI', 'PANR', 'PART',
    'PDPP', 'PLAN', 'PLAS', 'PMJS', 'POLU', 'POLL', 'POSA', 'PPRI',
    'PRAY', 'PRIM', 'PTDU', 'PTMR', 'PTPS', 'PTPW', 'PTSN', 'PURA',
    'PURE', 'PURI', 'RCCC', 'REAL', 'RELF', 'RGAS', 'RMKO', 'RONY',
    'RSCH', 'SAGE', 'SATU', 'SHID', 'SKRN', 'SMIL', 'SMKL', 'SMKM',
    'SMLE', 'SNLK', 'SRAJ', 'STAR', 'SUNI', 'SUPR', 'SWID', 'TAMU',
    'TAYS', 'TDPM', 'TFCO', 'TIRT', 'TLDN', 'TRUK', 'TYRE', 'UDNG',
    'UFOE', 'UNIQ', 'UNTD', 'VERN', 'WIDI', 'WINE', 'WINR', 'WMPP',
    'ZATA', 'ZONE', 'AMAN', 'ANDI', 'AYLS', 'CRAB', 'DEWI', 'DSFI',
    'ESTA', 'IFSH', 'ISEA', 'JARR', 'MGRO', 'MOLI', 'NAYZ', 'NSSS',
    'PNGO', 'SAMF', 'SPRE', 'BBRM', 'BESS', 'BLTA', 'BOAT', 'BSML',
    'BULL', 'ELTY', 'ENVY', 'ENZO', 'EPAC', 'ERAL', 'ESIP', 'EURO',
    'FWCT', 'GLVA', 'GMTD', 'GOLF', 'GOLL', 'GTSI', 'GULA', 'GUNA',
    'HAJJ', 'HALO', 'HBAT', 'HUMI', 'HYGN', 'IBFN', 'IBOS', 'IFII',
    'IKAI', 'IKAN', 'IKBI', 'IKPM', 'INCF', 'INPS', 'INTA', 'IPPE',
    'KARW', 'KAYU', 'KBAG', 'KBLV', 'KIAS', 'KICI', 'KING', 'KLAS',
    'KOCI', 'KOIN', 'KOKA', 'KONI', 'KRYA', 'KUAS', 'LABS', 'LFLO',
    'LIVE', 'LMAX', 'LMPI', 'LOPI', 'MAHA', 'MAXI', 'MDIY', 'MEDS',
    'MEJA', 'MENN', 'MGLV', 'MHKI', 'MMIX', 'MPIX', 'MSIE', 'MSJA',
    'MTMH', 'MTPS', 'NATO', 'NEST', 'NICK', 'NTBK', 'NUSA', 'OBMD',
    'OKAS', 'OLIV', 'OPMS', 'PADA', 'PEVE', 'PIPA', 'PMMP', 'RAFI',
    'SBAT', 'SBMA', 'SICO', 'SIMA', 'SMGA', 'SOFA', 'SOUL', 'SPTO',
    'STRK', 'TRAM', 'TRIL',
]

TICKERS_YF = [t + ".JK" for t in SAHAM_IHSG]

# ============================================================
# PARAMETER SMA
# ============================================================
SMA_KECIL = [3, 5, 10]            # SMA kecil / trigger
SMA_PENGGIRING = [20]             # SMA penggiring
SMA_BESAR = [60, 100, 200]        # SMA besar / level support-resistance

# ============================================================
# PARAMETER SCREENING
# ============================================================
LOOKBACK_DAILY = 250              # hari historis daily yang di-download

# Setup 1 -- spread maks antar SMA3, SMA5, SMA10 (melilit satu sama lain)
SMA_CLUSTER_TOLERANCE = 0.25      # 25% spread maks antar SMA kecil

# Setup 1 -- toleransi gap SMA20 ke cluster SMA kecil (tergantung harga saham)
SMA20_TOL_MAHAL = 0.50            # 50% -- saham harga >= 500
SMA20_TOL_MURAH = 0.30            # 30% -- saham harga < 500

# Setup 1 -- filter gap minimum SMA20 -> SMA Besar (target profit)
SMA20_TO_SMABT_MIN = 0.08         # 8% gap minimum

# Setup 2 -- maks jarak harga ke SMA Besar supaya dianggap "otw mendekati"
APPROACHING_PCT = 0.7

# Setup 3 -- volume harus di atas volume SMA 20
VOL_MULTIPLIER = 1.0

# ============================================================
# DATA OUTPUT
# ============================================================
DATA_DIR = "data"
LATEST_RESULT_FILE = "data/latest_result.json"
HISTORY_DIR = "data/history"
