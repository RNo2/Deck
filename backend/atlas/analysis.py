"""Descriptive, trailing-only research signals; no causal or trading claims."""
import numpy as np
from scipy import stats

def analyze(rows, frequency):
 if len(rows)<8:
  return {"status":"insufficient evidence","sample_size":len(rows),"minimum_observations":8,"findings":[]}
 values=np.array([r.value for r in rows],dtype=float)
 window=20 if frequency=="daily" else 10
 prior=values[-window-1:-1]
 sd=float(np.std(prior,ddof=1))
 z=float((values[-1]-np.mean(prior))/sd) if sd>0 else None
 regression=stats.linregress(np.arange(len(prior)),prior) if len(prior)>=3 else None
 interval=stats.t.ppf(.975,len(prior)-2)*regression.stderr if regression else None
 strength=min(abs(z)/3,1) if z is not None else 0
 components={"anomaly":round(strength*100,1),"history":round(min(len(rows)/30,1)*100,1),"corroboration":0}
 weights={"anomaly":.6,"history":.2,"corroboration":.2}
 score=round(sum(components[k]*weights[k] for k in weights),1)
 return {"status":"descriptive signal" if z is not None and abs(z)>=2 else "no unusual deviation", "sample_size":len(rows),"period":[rows[0].date,rows[-1].date],"latest":float(values[-1]),"change":float(values[-1]-values[-2]),"baseline_sample":len(prior),"baseline_mean":float(np.mean(prior)),"z_score":z,"priority":score,"components":components,"weights":weights,"evidence_confidence":"limited: one series, no independent corroboration","direction":"uncertain","slope":float(regression.slope) if regression else None,"slope_p_value":float(regression.pvalue) if regression and sd>0 else None,"slope_95_ci":[float(regression.slope-interval),float(regression.slope+interval)] if regression and sd>0 else None,"methodology":f"Latest level minus mean of preceding {len(prior)} observations, divided by their sample standard deviation. Latest observation excluded from baseline. Trend is OLS over that same baseline; slope units are per observation.","limitations":["Descriptive association is not causation or a forecast.","No multiple-testing correction; ranked candidates require independent investigation.","Serial correlation may invalidate conventional OLS confidence intervals.","Revised current-vintage history is not suitable for point-in-time backtesting.","Priority is research triage, not a probability of investment success."]}
