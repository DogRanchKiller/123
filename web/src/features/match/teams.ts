/**
 * 球队展示：本库队名（football-data 写法）→ 中文名与队徽。只改显示，不参与任何计算。
 * 队徽由 `_diag/web_crests.py` 从 FotMob 下载到 public/crests/{id}.png，crests.json 记队名 → FotMob 球队 id。
 * 表里没有的队（升班马等）显示原名，队徽位置用名字前两个字。
 */
import crests from "./crests.json";

const ZH: Readonly<Record<string, string>> = {
  // 英超
  Arsenal: "阿森纳", "Aston Villa": "阿斯顿维拉", Bournemouth: "伯恩茅斯", Brentford: "布伦特福德",
  Brighton: "布莱顿", Chelsea: "切尔西", Coventry: "考文垂", "Crystal Palace": "水晶宫",
  Everton: "埃弗顿", Fulham: "富勒姆", Hull: "赫尔城", Ipswich: "伊普斯维奇",
  Leeds: "利兹联", Liverpool: "利物浦", "Man City": "曼城", "Manchester Utd": "曼联",
  "Man United": "曼联", Newcastle: "纽卡斯尔", "Nott'm Forest": "诺丁汉森林",
  Sunderland: "桑德兰", Tottenham: "热刺",
  // 英冠
  Birmingham: "伯明翰", Blackburn: "布莱克本", Bolton: "博尔顿", "Bristol City": "布里斯托城",
  Burnley: "伯恩利", Cardiff: "卡迪夫城", Charlton: "查尔顿", Derby: "德比郡",
  Lincoln: "林肯城", Middlesbrough: "米德尔斯堡", Millwall: "米尔沃尔", Norwich: "诺维奇",
  Portsmouth: "朴茨茅斯", Preston: "普雷斯顿", QPR: "女王公园巡游者", "Sheffield United": "谢菲尔德联",
  Southampton: "南安普顿", Stoke: "斯托克城", Swansea: "斯旺西", Watford: "沃特福德",
  "West Brom": "西布朗", "West Ham": "西汉姆联", Wolverhampton: "狼队", Wolves: "狼队",
  Wrexham: "雷克瑟姆",
  // 德甲
  Augsburg: "奥格斯堡", "Bayern Munich": "拜仁慕尼黑", Dortmund: "多特蒙德", "Ein Frankfurt": "法兰克福",
  Elversberg: "埃尔弗斯贝格", "FC Koln": "科隆", Freiburg: "弗赖堡", Hamburg: "汉堡",
  Hoffenheim: "霍芬海姆", Leverkusen: "勒沃库森", "M'gladbach": "门兴格拉德巴赫", Mainz: "美因茨",
  Paderborn: "帕德博恩", "RB Leipzig": "莱比锡", "Schalke 04": "沙尔克04", Stuttgart: "斯图加特",
  "Union Berlin": "柏林联合", "Werder Bremen": "云达不莱梅",
  // 西甲
  Alaves: "阿拉维斯", "Ath Bilbao": "毕尔巴鄂竞技", "Ath Madrid": "马德里竞技", Barcelona: "巴塞罗那",
  Betis: "皇家贝蒂斯", Celta: "塞尔塔", Elche: "埃尔切", Espanol: "西班牙人", Getafe: "赫塔菲",
  "La Coruna": "拉科鲁尼亚", Levante: "莱万特", Malaga: "马拉加", Osasuna: "奥萨苏纳",
  "Real Madrid": "皇家马德里", Santander: "桑坦德竞技", Sevilla: "塞维利亚", Sociedad: "皇家社会",
  Valencia: "瓦伦西亚", Vallecano: "巴列卡诺", Villarreal: "比利亚雷亚尔",
  // 意甲
  Atalanta: "亚特兰大", Bologna: "博洛尼亚", Cagliari: "卡利亚里", Como: "科莫",
  Fiorentina: "佛罗伦萨", Frosinone: "弗洛西诺内", Genoa: "热那亚", Inter: "国际米兰",
  Juventus: "尤文图斯", Lazio: "拉齐奥", Lecce: "莱切", Milan: "AC米兰", Monza: "蒙扎",
  Napoli: "那不勒斯", Parma: "帕尔马", Roma: "罗马", Sassuolo: "萨索洛", Torino: "都灵",
  Udinese: "乌迪内斯", Venezia: "威尼斯",
  // 法甲
  Angers: "昂热", Auxerre: "欧塞尔", Brest: "布雷斯特", "Le Havre": "勒阿弗尔", "Le Mans": "勒芒",
  Lens: "朗斯", Lille: "里尔", Lorient: "洛里昂", Lyon: "里昂", Marseille: "马赛", Monaco: "摩纳哥",
  Nice: "尼斯", "Paris FC": "巴黎FC", "Paris SG": "巴黎圣日耳曼", Rennes: "雷恩",
  Strasbourg: "斯特拉斯堡", Toulouse: "图卢兹", Troyes: "特鲁瓦",
  // 荷甲
  "AZ Alkmaar": "阿尔克马尔", Ajax: "阿贾克斯", Cambuur: "坎布尔", "Den Haag": "海牙",
  Excelsior: "精英队", Feyenoord: "费耶诺德", "For Sittard": "锡塔德", "Go Ahead Eagles": "前进之鹰",
  Groningen: "格罗宁根", Heerenveen: "海伦芬", Nijmegen: "奈梅亨", "PSV Eindhoven": "埃因霍温",
  "Sparta Rotterdam": "鹿特丹斯巴达", Telstar: "特尔斯达", Twente: "特温特", Utrecht: "乌得勒支",
  "Willem II": "威廉二世", Zwolle: "兹沃勒",
  // 葡超
  "Academico Viseu": "维塞乌学术", Alverca: "阿尔维卡", Arouca: "阿罗卡", Benfica: "本菲卡",
  "Casa Pia": "卡萨皮亚", Estoril: "埃斯托里尔", Estrela: "阿马多拉之星", Famalicao: "法马利康",
  "Gil Vicente": "吉尔维森特", Guimaraes: "吉马良斯", Maritimo: "马里迪莫", Moreirense: "莫雷伦斯",
  Nacional: "国民队", Porto: "波尔图", "Rio Ave": "里奥阿维", "Santa Clara": "圣克拉拉",
  "Sp Braga": "布拉加", "Sp Lisbon": "葡萄牙体育",
  // 苏超
  Aberdeen: "阿伯丁", Celtic: "凯尔特人", Dundee: "邓迪", "Dundee United": "邓迪联",
  Falkirk: "福尔柯克", Hearts: "哈茨", Hibernian: "希伯尼安", Kilmarnock: "基尔马诺克",
  Motherwell: "马瑟韦尔", Rangers: "流浪者", "St Johnstone": "圣约翰斯通", "St Mirren": "圣米伦",
  // 比甲
  Anderlecht: "安德莱赫特", Antwerp: "安特卫普", Beveren: "贝弗伦", "Cercle Brugge": "布鲁日瑟克尔",
  Charleroi: "沙勒罗瓦", "Club Brugge": "布鲁日", Genk: "亨克", Gent: "根特", Kortrijk: "科特赖克",
  "Lommel SK": "洛默尔", Mechelen: "梅赫伦", "Oud-Heverlee Leuven": "鲁汶",
  "RAAL La Louviere": "拉卢维耶尔", "St Truiden": "圣特鲁登", "St. Gilloise": "圣吉尔联合",
  Standard: "标准列日", Waregem: "瓦雷赫姆", Westerlo: "韦斯特洛",
  // 土超
  Alanyaspor: "阿拉尼亚体育", Amedspor: "阿梅德体育", Besiktas: "贝西克塔斯",
  Buyuksehyr: "伊斯坦布尔巴沙克", Corum: "乔鲁姆", Erzurumspor: "埃尔祖鲁姆体育",
  Eyupspor: "埃于普体育", Fenerbahce: "费内巴切", Galatasaray: "加拉塔萨雷", Gaziantep: "加济安泰普",
  Genclerbirligi: "根克勒比利吉", Goztep: "格兹泰佩", Kasimpasa: "卡斯帕萨", Kocaelispor: "科贾埃利体育",
  Konyaspor: "科尼亚体育", Rizespor: "里泽体育", Samsunspor: "萨姆松体育", Trabzonspor: "特拉布宗体育",
};

const CRESTS: Readonly<Record<string, string>> = crests;

/** 中文队名；表里没有时原样返回。 */
export function teamZh(name: string): string {
  return ZH[name] ?? name;
}

/** 队徽地址；没有下载到时为空。 */
export function crestOf(name: string): string | null {
  const id = CRESTS[name];
  return id ? `/crests/${id}.png` : null;
}

/** 没有队徽时的文字标记：中文名取前两个字，其余取英文首字母。 */
export function teamShort(name: string): string {
  const zh = ZH[name];
  if (zh) return zh.slice(0, 2);
  const words = name.split(/[\s.\-']+/).filter(Boolean);
  const short =
    words.length > 1 ? words.map((word) => word[0]).join("") : name.slice(0, 3);
  return short.slice(0, 3).toUpperCase();
}
