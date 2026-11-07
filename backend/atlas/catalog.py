COUNTRIES = {"BRA": "Brazil", "CHN": "China", "IND": "India", "ZAF": "South Africa", "USA": "United States", "DEU": "Germany", "JPN": "Japan", "MEX": "Mexico"}
INDICATORS = {"FP.CPI.TOTL.ZG": ("Consumer price inflation", "% annual", "inflation"), "NY.GDP.MKTP.KD.ZG": ("Real GDP growth", "% annual", "growth"), "NE.EXP.GNFS.ZS": ("Exports of goods and services", "% GDP", "trade")}
SOURCES = {
 "worldbank": {"name": "World Bank · World Development Indicators", "url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392", "frequency": "annual", "limitations": "Annual releases are delayed and revised. Retrieval dates are not publication dates. Current vintages cannot support point-in-time backtests."},
 "ecb": {"name": "European Central Bank · reference exchange rates", "url": "https://data.ecb.europa.eu/help/api/overview", "frequency": "daily", "limitations": "Business-day reference rates, not executable or real-time quotes. Historical values may be revised."},
 "csv": {"name": "User-supplied CSV", "url": "", "frequency": "declared on import", "limitations": "User-supplied observations are unverified. Source and units must be supplied."}
}
def catalog():
 result=[]
 for country, label in COUNTRIES.items():
  for code,(name,unit,category) in INDICATORS.items():
   result.append(dict(id=f"wb:{country}:{code}",name=f"{label} · {name}",country=country,category=category,unit=unit,frequency="annual",provider="worldbank"))
 for currency in ["USD","GBP","JPY","CHF","CNY","BRL","INR","ZAR"]:
  result.append(dict(id=f"ecb:{currency}",name=f"EUR / {currency}",country="Global",category="foreign exchange",unit=f"{currency} per EUR",frequency="daily",provider="ecb"))
 return result
