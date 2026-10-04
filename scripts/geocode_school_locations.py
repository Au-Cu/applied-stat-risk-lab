"""One-time, cached campus geocoding for the public school map.

The script follows the public Nominatim usage policy: one process, one request at
a time, at least 1.1 seconds between requests, a descriptive User-Agent, and a
local cache. The generated CSV is committed so the public website never calls a
geocoder at runtime.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHOOLS = ROOT / "data" / "processed" / "schools.csv"
OUTPUT = ROOT / "data" / "source" / "school_locations_osm.csv"
CACHE = ROOT / "work" / "nominatim_school_locations.json"

USER_AGENT = "AppliedStatRiskLab/0.2 (https://github.com/Au-Cu/applied-stat-risk-lab)"
ENDPOINT = "https://nominatim.openstreetmap.org/search"

QUERY_OVERRIDES = {
    "南京大学": "南京大学 仙林校区",
    "华东师范大学": "华东师范大学 闵行校区",
    "上海交通大学": "上海交通大学 闵行校区",
    "中国科学技术大学": "中国科学技术大学 东校区",
    "四川大学": "四川大学 望江校区",
    "复旦大学": "复旦大学 邯郸校区",
    "东南大学": "东南大学 九龙湖校区",
    "清华大学": "清华大学 清华园",
    "华中科技大学": "华中科技大学 主校区",
    "北京师范大学": "北京师范大学 珠海校区",
    "吉林大学": "吉林大学 前卫南区",
    "兰州大学": "兰州大学 一分部",
    "西安交通大学": "西安交通大学 兴庆校区",
    "中南大学": "中南大学 校本部",
    "重庆大学": "重庆大学 A区",
    "西北工业大学": "西北工业大学 长安校区",
    "大连理工大学": "大连理工大学 凌水校区",
    "东北大学": "东北大学 沈阳 南湖校区",
    "中国人民大学": "中国人民大学 中关村校区",
    "哈尔滨工业大学": "哈尔滨工业大学 哈尔滨校区",
    "合肥工业大学": "合肥工业大学 屯溪路校区",
    "中山大学": "中山大学 广州校区南校园",
    "厦门大学": "厦门大学 思明校区",
    "山东大学": "山东大学 中心校区 济南",
    "武汉大学": "武汉大学 珞珈山",
    "太原理工大学": "太原理工大学 迎西校区",
    "上海财经大学": "上海财经大学 国定路校区",
    "西南财经大学": "西南财经大学 柳林校区",
    "中央财经大学": "中央财经大学 学院南路校区",
    "湖南大学": "湖南大学 财院校区",
    "对外经济贸易大学": "对外经济贸易大学 惠新东街",
    "同济大学": "同济大学 四平路校区",
    "中南财经政法大学": "中南财经政法大学 南湖校区",
    "国防科技大学": "国防科技大学 三号院 长沙",
    "西安电子科技大学": "西安电子科技大学 南校区",
    "南京航空航天大学": "南京航空航天大学 将军路校区",
    "南京理工大学": "南京理工大学 孝陵卫校区",
    "中国海洋大学": "中国海洋大学 崂山校区",
    "暨南大学": "暨南大学 石牌校区",
    "北京交通大学": "北京交通大学 上园村",
    "华东理工大学": "华东理工大学 徐汇校区",
    "上海大学": "上海大学 宝山校区",
    "苏州大学": "苏州大学 天赐庄校区",
    "河海大学": "河海大学 江宁校区",
    "武汉理工大学": "武汉理工大学 马房山校区",
    "东北师范大学": "东北师范大学 净月校区",
    "东华大学": "东华大学 松江校区",
    "北京工业大学": "北京工业大学 平乐园校区",
    "郑州大学": "郑州大学 主校区",
    "华南师范大学": "华南师范大学 石牌校区",
    "华中师范大学": "华中师范大学 桂子山校区",
    "西南交通大学": "西南交通大学 犀浦校区",
    "西北大学": "西北大学 长安校区",
    "中国石油大学（北京）": "中国石油大学 北京 昌平校区",
    "华北电力大学": "华北电力大学 北京校部",
    "南京师范大学": "南京师范大学 仙林校区",
    "中国石油大学（华东）": "中国石油大学 华东 唐岛湾校区",
    "中国地质大学（武汉）": "中国地质大学 武汉 南望山校区",
    "中国地质大学（北京）": "中国地质大学 北京 学院路",
    "福州大学": "福州大学 旗山校区",
    "西南大学": "西南大学 北碚校区",
    "陕西师范大学": "陕西师范大学 长安校区",
    "中央民族大学": "中央民族大学 中关村校区",
    "辽宁大学": "辽宁大学 崇山校区",
    "湖南师范大学": "湖南师范大学 二里半校区",
    "北京林业大学": "北京林业大学 清华东路",
    "河北工业大学": "河北工业大学 北辰校区",
    "中国药科大学": "中国药科大学 江宁校区",
    "南昌大学": "南昌大学 前湖校区",
    "华中农业大学": "华中农业大学 狮子山",
    "安徽大学": "安徽大学 磬苑校区",
    "南京农业大学": "南京农业大学 卫岗校区",
    "东北农业大学": "东北农业大学 香坊区",
    "东北林业大学": "东北林业大学 香坊区",
    "延边大学": "延边大学 延吉",
    "云南大学": "云南大学 呈贡校区",
    "贵州大学": "贵州大学 西校区",
    "内蒙古大学": "内蒙古大学 赛罕区",
    "新疆大学": "新疆大学 博达校区",
    "宁夏大学": "宁夏大学 贺兰山校区",
    "石河子大学": "石河子大学 北四路校区",
}

# A small number of Nominatim's first-ranked results resolve to a similarly
# named school, a transit stop, or an internal campus building. These reviewed
# choices pin the intended campus while retaining a public source URL.
MANUAL_MATCHES = {
    "兰州大学": {
        "latitude": "36.0466460", "longitude": "103.8611840",
        "matched_name": "兰州大学城关校区东区（一分部），甘肃省兰州市城关区天水南路222号",
        "source": "OpenStreetMap campus-area match", "source_url": "https://www.openstreetmap.org/way/303425302",
        "precision": "campus_area",
    },
    "中南大学": {
        "latitude": "28.1692907", "longitude": "112.9285200",
        "matched_name": "中南大学校本部，湖南省长沙市岳麓区",
        "source": "OpenStreetMap campus-area match", "source_url": "https://www.openstreetmap.org/way/644418434",
        "precision": "campus_area",
    },
    "重庆大学": {
        "latitude": "29.5699522", "longitude": "106.4596103",
        "matched_name": "重庆大学A区，重庆市沙坪坝区沙坪坝正街174号",
        "source": "OpenStreetMap campus entrance", "source_url": "https://www.openstreetmap.org/node/10180144507",
        "precision": "campus_entrance",
    },
    "哈尔滨工业大学": {
        "latitude": "45.7415890", "longitude": "126.6255626",
        "matched_name": "哈尔滨工业大学校本部，黑龙江省哈尔滨市南岗区西大直街92号",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/relation/13053921",
        "precision": "campus",
    },
    "厦门大学": {
        "latitude": "24.4399419", "longitude": "118.0930178",
        "matched_name": "厦门大学思明校区，福建省厦门市思明区思明南路422号",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/way/154986493",
        "precision": "campus",
    },
    "武汉大学": {
        "latitude": "30.5373773", "longitude": "114.3615350",
        "matched_name": "武汉大学珞珈山校区，湖北省武汉市武昌区八一路299号",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/relation/10717504",
        "precision": "campus",
    },
    "中央财经大学": {
        "latitude": "39.9581476", "longitude": "116.3362796",
        "matched_name": "中央财经大学学院南路校区，北京市海淀区学院南路39号",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/way/248393687",
        "precision": "campus",
    },
    "国防科技大学": {
        "latitude": "28.2596800", "longitude": "113.0425000",
        "matched_name": "国防科技大学三号院，湖南省长沙市开福区福元路1号",
        "source": "OpenStreetMap campus", "source_url": "https://www.openstreetmap.org/way/1301509862",
        "precision": "campus",
    },
    "北京交通大学": {
        "latitude": "39.9501000", "longitude": "116.3371000",
        "matched_name": "北京交通大学校本部，北京市海淀区上园村3号",
        "source": "OpenStreetMap campus-area match", "source_url": "https://www.openstreetmap.org/node/2108372992",
        "precision": "campus_area",
    },
    "武汉理工大学": {
        "latitude": "30.5217340", "longitude": "114.3506960",
        "matched_name": "武汉理工大学马房山校区西院，湖北省武汉市洪山区珞狮路122号",
        "source": "高德地图公开地点页", "source_url": "https://ditu.amap.com/place/B001B0IYJV",
        "precision": "campus_entrance",
    },
    "郑州大学": {
        "latitude": "34.8088168", "longitude": "113.5352664",
        "matched_name": "郑州大学主校区，河南省郑州市科学大道100号",
        "source": "OpenStreetMap campus entrance", "source_url": "https://www.openstreetmap.org/node/4608190663",
        "precision": "campus_entrance",
    },
    "华北电力大学": {
        "latitude": "40.0881244", "longitude": "116.3035388",
        "matched_name": "华北电力大学北京校部，北京市昌平区北农路2号",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/way/48049618",
        "precision": "campus",
    },
    "西南大学": {
        "latitude": "29.8232372", "longitude": "106.4195884",
        "matched_name": "西南大学北碚校区，重庆市北碚区天生路2号",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/way/413071891",
        "precision": "campus",
    },
    "南昌大学": {
        "latitude": "28.6572190", "longitude": "115.7931408",
        "matched_name": "南昌大学前湖校区，江西省南昌市红谷滩区学府大道999号",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/way/223390772",
        "precision": "campus",
    },
    "贵州大学": {
        "latitude": "26.4495922", "longitude": "106.6540260",
        "matched_name": "贵州大学西校区，贵州省贵阳市花溪区甲秀南路",
        "source": "OpenStreetMap Nominatim", "source_url": "https://www.openstreetmap.org/relation/12845727",
        "precision": "campus",
    },
    "内蒙古大学": {
        "latitude": "40.8087054", "longitude": "111.6837240",
        "matched_name": "内蒙古大学北校区，内蒙古自治区呼和浩特市赛罕区大学西街235号",
        "source": "OpenStreetMap campus entrance", "source_url": "https://www.openstreetmap.org/node/13108698977",
        "precision": "campus_entrance",
    },
}


def fetch(query: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 3,
            "countrycodes": "cn",
            "accept-language": "zh-CN",
        }
    )
    request = urllib.request.Request(
        f"{ENDPOINT}?{params}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="ignore cached responses")
    args = parser.parse_args()

    with SCHOOLS.open(encoding="utf-8-sig", newline="") as handle:
        schools = list(csv.DictReader(handle))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = {} if args.refresh or not CACHE.exists() else json.loads(CACHE.read_text(encoding="utf-8"))

    rows = []
    for index, school_row in enumerate(schools):
        school = school_row["school"]
        query = QUERY_OVERRIDES.get(school, school)
        if query not in cache:
            if cache:
                time.sleep(1.1)
            results = fetch(query)
            if not results and query != school:
                time.sleep(1.1)
                results = fetch(school)
            cache[query] = results
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        results = cache[query]
        best = results[0] if results else {}
        manual = MANUAL_MATCHES.get(school, {})
        latitude = manual.get("latitude", best.get("lat", ""))
        longitude = manual.get("longitude", best.get("lon", ""))
        matched_name = manual.get("matched_name", best.get("display_name", ""))
        precision = manual.get(
            "precision", "campus" if best.get("type") in {"university", "college"} else "poi_or_area"
        )
        source = manual.get("source", "OpenStreetMap Nominatim")
        source_url = manual.get("source_url") or (
            f"https://www.openstreetmap.org/{best.get('osm_type', '').lower()}/{best.get('osm_id', '')}"
            if best.get("osm_type") and best.get("osm_id")
            else ""
        )
        rows.append(
            {
                "school": school,
                "campus_label": school_row.get("location") or "",
                "latitude": latitude,
                "longitude": longitude,
                "matched_name": matched_name,
                "query": query,
                "precision": precision,
                "source": source,
                "source_url": source_url,
                "review_status": "机器匹配待人工复核",
            }
        )
        print(f"{index + 1:02d}/{len(schools)} {school}: {matched_name or 'NO MATCH'}")

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
