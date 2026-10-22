"""Nine direct horizons with archived forecast weather and ordered quantiles."""
import numpy as np
import torch
from torch import nn
from train_station_tcn import CausalBlock

WX=['temperature_2m','relative_humidity_2m','surface_pressure','wind_speed_10m','precipitation','wind_direction_sin','wind_direction_cos']
HORIZONS=9

class ForecastTCN(nn.Module):
    def __init__(self,inputs,channels=48,use_future=True):
        super().__init__();self.use_future=use_future;layers=[]
        for d in [1,2,4,8,16,32]:layers.append(CausalBlock(inputs,channels,d));inputs=channels
        self.encoder=nn.Sequential(*layers)
        self.weather=nn.Sequential(nn.Linear(7,24),nn.GELU(),nn.Linear(24,24))
        self.horizon=nn.Embedding(HORIZONS,8)
        self.head=nn.Sequential(nn.Linear(channels+24+8,48),nn.GELU(),nn.Linear(48,3))
    def forward(self,x,weather):
        encoded=self.encoder(x)[:,:,-1,None].transpose(1,2).expand(-1,HORIZONS,-1)
        w=self.weather(weather) if self.use_future else torch.zeros((len(x),HORIZONS,24),device=x.device,dtype=x.dtype)
        h=self.horizon(torch.arange(HORIZONS,device=x.device)).expand(len(x),-1,-1)
        raw=self.head(torch.cat([encoded,w,h],dim=2));median=raw[:,:,0]
        return torch.stack([median-nn.functional.softplus(raw[:,:,1]),median,median+nn.functional.softplus(raw[:,:,2])],dim=2)

def conformal_adjustment(lower,upper,actual,coverage=.8):
    scores=np.maximum(np.maximum(lower-actual,actual-upper),0.)
    scores=scores[np.isfinite(scores)]
    if not len(scores):raise ValueError('Calibration requires genuine held-out targets')
    rank=min(len(scores),int(np.ceil((len(scores)+1)*coverage)))
    return float(np.sort(scores)[rank-1])

def add_intervals(prediction,lower,upper,adjustment):
    prediction=np.maximum(0.,prediction)
    return prediction,np.maximum(0.,np.minimum(lower-adjustment,prediction)),np.maximum(upper+adjustment,prediction)
