<script setup>
import {computed,onMounted,onBeforeUnmount,ref,watch} from 'vue'
import {Activity,RefreshCw,Download,Clock3,Wind,Info,ArrowUpRight} from '@lucide/vue'
import Chart from '../components/Chart.vue'
import {api,fmt,baseChart} from '../lib/api'
const props=defineProps({meta:Object})
const live=ref(null),forecast=ref(null),selected=ref('mean'),error=ref(''),notice=ref(''),requesting=ref(false),clock=ref(Date.now()),weather=ref('wind_speed_10m'),reference=ref(75)
const phases={initializing:'初始化实时连接',collecting:'采集最新实测和天气资料',spark:'Spark 清洗与 72 小时特征融合',inference:'运行 TCN 并发布未来六小时预测',complete:'更新完成',failed:'本轮更新未完成'}
const wx={wind_speed_10m:['风速','m/s'],temperature_2m:['气温','°C'],relative_humidity_2m:['相对湿度','%'],surface_pressure:['气压','hPa'],precipitation:['降水','mm'],wind_direction_10m:['风向','°']}
const dateFormat=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})
const stamp=t=>t?dateFormat.format(new Date(t)):'—'
const short=t=>t?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(t)):'—'
const fresh=computed(()=>live.value?.usable&&forecast.value?.points.every(p=>new Date(p.target).getTime()>clock.value))
const age=computed(()=>live.value?.origin?(clock.value-new Date(live.value.origin))/60000:null)
const risk=computed(()=>{const limit=Number(reference.value);if(!forecast.value||!Number.isFinite(limit))return '';const med=forecast.value.points.filter(p=>p.prediction>=limit);const upper=forecast.value.points.filter(p=>p.upper!=null&&p.upper>=limit);return med.length?`有 ${med.length} 个目标的预测中位数达到参考线 ${limit} μg/m³。`:upper.length?`有 ${upper.length} 个目标的区间上沿超过参考线 ${limit} μg/m³，需结合后续更新观察。`:'本轮中位预测与区间上沿均未达到所设参考线。'})
const currentWeather=computed(()=>forecast.value?.history.at(-1))
const phase=computed(()=>live.value?.refreshing&&live.value?.refresh.phase==='complete'?'正在启动数据采集':phases[live.value?.refresh.phase]||'正在更新')
const refreshing=computed(()=>requesting.value||live.value?.refreshing)
let pollTimer,clockTimer,token=0,lastCycle=''
async function loadForecast(){
  const id=++token
  if(!live.value?.usable){forecast.value=null;return}
  try{const f=await api('live/forecast',{station_id:selected.value});if(id===token){forecast.value=f;error.value=''}}catch(e){if(id===token){forecast.value=null;error.value=e.message}}
}
async function poll(){
  try{
    const m=await api('live/meta');live.value=m
    if(selected.value!=='mean'&&!m.stations.some(s=>s.station_id===selected.value&&s.available))selected.value='mean'
    if(m.cycle_id!==lastCycle&&notice.value==='已开始更新实时数据与六小时预测')notice.value='最新实测与预测已更新'
    if(m.cycle_id!==lastCycle||!forecast.value){lastCycle=m.cycle_id;await loadForecast()}
  }catch(e){error.value=e.message}
}
async function refresh(){
  requesting.value=true;notice.value=''
  try{const r=await fetch('/api/live/refresh',{method:'POST'});const body=await r.json();if(!r.ok)throw new Error(body.detail||'更新未能启动');notice.value=body.message;await poll()}catch(e){error.value=e.message}finally{requesting.value=false}
}
watch(selected,loadForecast)
onMounted(async()=>{await poll();pollTimer=setInterval(poll,5000);clockTimer=setInterval(()=>clock.value=Date.now(),1000)})
onBeforeUnmount(()=>{clearInterval(pollTimer);clearInterval(clockTimer)})
const forecastOption=computed(()=>{
  const f=forecast.value;if(!f)return {...baseChart}
  const initial=[f.origin,f.current]
  const bands=f.points.every(p=>p.lower!=null)?[{name:'区间下沿',type:'line',stack:'band',symbol:'none',silent:true,tooltip:{show:false},lineStyle:{opacity:0},data:[[f.origin,f.current],...f.points.map(p=>[p.target,p.lower])]},{name:'80%名义区间',type:'line',stack:'band',symbol:'none',silent:true,tooltip:{show:false},lineStyle:{opacity:0},areaStyle:{color:'#176e5926'},data:[[f.origin,0],...f.points.map(p=>[p.target,p.upper-p.lower])]}]:[]
  return {...baseChart,tooltip:{...baseChart.tooltip,valueFormatter:v=>fmt(Array.isArray(v)?v[1]:v,1)+' μg/m³'},grid:{...baseChart.grid,bottom:58},xAxis:{...baseChart.xAxis,type:'time',axisLabel:{formatter:v=>stamp(v),hideOverlap:true,color:'#82917f'}},
    dataZoom:[{type:'inside',start:60,end:100},{type:'slider',start:60,end:100,height:13,bottom:0,borderColor:'transparent'}],
    series:[...bands,{name:'历史实测',type:'line',showSymbol:false,data:f.history.map(p=>[p.ts,p.pm25]),lineStyle:{color:'#7d9b8b',width:1.8},itemStyle:{color:'#7d9b8b'}},
      {name:'当前预测',type:'line',data:[initial,...f.points.map(p=>({value:[p.target,p.prediction],itemStyle:{color:p.method==='recursive_extension'?'#c58e4b':'#176e59'}}))],symbolSize:6,lineStyle:{color:'#176e59',width:2.7},itemStyle:{color:'#176e59'},markLine:{silent:true,symbol:'none',lineStyle:{color:'#ba9b6e',type:'dashed'},label:{formatter:'自设参考线'},data:[{yAxis:Number(reference.value)||75}]}},
      {name:'持续基线',type:'line',showSymbol:false,data:[initial,...f.points.map(p=>[p.target,p.baseline])],lineStyle:{color:'#b4baaa',width:1.5,type:'dashed'},itemStyle:{color:'#b4baaa'}}]}
})
const weatherOption=computed(()=>({...baseChart,xAxis:{...baseChart.xAxis,type:'time',axisLabel:{formatter:v=>stamp(v)}},yAxis:{...baseChart.yAxis,name:wx[weather.value][1]},series:[{type:weather.value==='precipitation'?'bar':'line',showSymbol:false,data:forecast.value?.history.map(p=>[p.ts,p[weather.value]])||[],lineStyle:{width:2,color:'#71937b'},itemStyle:{color:'#71937b'}}]}))
const mapOption=computed(()=>({tooltip:{formatter:p=>`${p.data.name}<br/>PM₂.₅ ${fmt(p.value[2])} μg/m³`},geo:{map:'bth-region',roam:true,center:[116.4074,39.9042],zoom:3.2,layoutCenter:['47%','49%'],layoutSize:'95%',scaleLimit:{min:.8,max:12},itemStyle:{areaColor:'#eff3e9',borderColor:'#d2dccd'},emphasis:{disabled:true}},visualMap:{show:false,dimension:2,min:0,max:150,inRange:{color:['#4a987a','#bcc179','#d8ac60','#bc6551']}},series:[{type:'scatter',coordinateSystem:'geo',data:(live.value?.stations||[]).filter(s=>s.current!=null&&s.latitude!=null&&s.longitude!=null).map(s=>({name:`${s.station_id} ${s.name}`,station_id:s.station_id,value:[s.longitude,s.latitude,s.current],symbolSize:s.station_id===selected.value?15:10,itemStyle:{borderColor:s.station_id===selected.value?'#244d3e':'#fff',borderWidth:1.5}})),label:{show:true,position:'right',formatter:p=>p.data.station_id,color:'#617258',fontSize:10},labelLayout:{hideOverlap:true}}]}))
function mapSelect(p){if(live.value.stations.some(s=>s.station_id===p.data?.station_id&&s.available))selected.value=p.data.station_id}
const exportHref=computed(()=>'/api/live/export?'+new URLSearchParams({station_id:selected.value}))
</script>
<template>
  <div v-if="error" class="error-box" role="alert">{{ error }}</div>
  <div v-if="!live" class="page-loader"><span class="spinner"></span>正在连接实时预测服务…</div>
  <template v-else>
    <section class="live-status panel"><div><span class="live-dot" :class="{muted:!live.usable}"></span><strong>{{ live.usable?'最新实测已接入':'正在准备当前预测' }}</strong><span class="live-clock"><Clock3 :size="13" />北京时间 {{ stamp(clock) }}</span><p>服务运行时每 10 分钟更新，并在整点后重新生成未来窗口。</p></div><button class="button primary" :disabled="refreshing" @click="refresh"><RefreshCw :size="15" :class="{'live-spinning':refreshing}" />{{ refreshing?'正在更新':'更新实测与预测' }}</button></section>
    <div v-if="notice" class="info-box" role="status">{{ notice }}</div>
    <div v-if="live.refreshing" class="info-box" role="status"><span class="spinner"></span>{{ phase }}。可继续查看尚未过期的上一轮结果。</div>
    <div v-if="live.refresh.phase==='failed'" class="error-box" role="alert">{{ live.refresh.error }}。{{ live.usable?'当前显示上一轮尚未过期的结果。':'数据恢复后将重新生成预测。' }}</div>
    <div v-if="live.source_errors?.length" class="info-box">部分原始资料本轮未获取，当前结果使用已成功取得的资料；请结合实测时刻和站点覆盖数查看。</div>
    <section v-if="!live.ready" class="panel"><h2>正在建立最近 72 小时的实时输入</h2><p class="station-copy">{{ phase }}。首次需要补充最近几日站点记录，随后由 Spark 构建小时网格并运行已训练模型。</p><p class="station-copy">空气质量：中国环境监测总站 + quotsoft 近几日归档；气象：Open-Meteo 业务天气模型。</p></section>
    <template v-else>
      <section class="kpi-grid"><article class="kpi-card featured"><div class="kpi-label">北京覆盖站点实测均值<Activity :size="15" /></div><div class="kpi-number">{{ fmt(live.current) }}<small>μg/m³</small></div><div class="kpi-bottom">观测时刻 {{ stamp(live.origin) }}</div></article><article class="kpi-card"><div class="kpi-label">最新实测距现在<Clock3 :size="15" /></div><div class="kpi-number">{{ fmt(age,0) }}<small>分钟</small></div><div class="kpi-bottom">按数据时间计算，发布存在延迟</div></article><article class="kpi-card"><div class="kpi-label">当前可预测北京站点</div><div class="kpi-number">{{ live.forecast_stations }}<small>/ {{ live.beijing_stations }} 个已训练站点</small></div><div class="kpi-bottom">起点实测 + 至少 48 个历史有效小时</div></article><article class="kpi-card"><div class="kpi-label">模型使用的起点天气<Wind :size="15" /></div><div class="kpi-number">{{ fmt(currentWeather?.temperature_2m) }}<small>°C</small></div><div class="kpi-bottom">风 {{ fmt(currentWeather?.wind_speed_10m) }} m/s · 湿度 {{ fmt(currentWeather?.relative_humidity_2m,0) }}%</div></article></section>
      <section class="panel live-selector"><label class="form-field">预测范围<select v-model="selected" aria-label="实时预测站点"><option value="mean">北京覆盖站点均值（{{ live.forecast_stations }} 站）</option><option v-for="s in live.stations" :key="s.station_id" :value="s.station_id" :disabled="!s.available">{{ s.station_id }} · {{ s.name }}{{ s.available?'':' · 暂不可预测' }}</option></select></label><div class="live-origin"><span>最新实测 {{ stamp(live.origin) }}</span><span>预测发布 {{ stamp(live.issued_at) }}</span><span v-if="live.next_refresh">下次更新约 {{ short(live.next_refresh) }}</span></div><a v-if="fresh" class="button secondary small" :href="exportHref"><Download :size="14" />导出当前预测</a></section>
      <div v-if="!fresh" class="info-box" role="status">上一轮预测已过期或资料正在准备，正在等待新的当前预测。实测超过三小时将停止发布。</div>
      <template v-if="fresh">
        <section class="panel"><div class="panel-heading"><div><div class="section-kicker">LIVE SIX-HOUR FORECAST</div><h2>{{ forecast.name }}：未来六个整点</h2></div><span class="subtle-tag">{{ live.future_weather?'TCN · 72h历史 + 未来天气':'TCN · 最近72小时' }}</span></div><div class="chart-legend"><span><i style="background:#7d9b8b"></i>历史实测</span><span><i style="background:#176e59"></i>当前预测</span><span><i style="background:#b4baaa"></i>持续基线</span><span v-if="live.extension_hours"><i style="background:#c58e4b"></i>递推延伸</span><span v-if="live.nominal_coverage"><i style="background:#176e5933"></i>80%名义区间</span></div><Chart :option="forecastOption" height="330px" label="当前北京未来六个整点PM2.5预测" /><div class="table-scroll"><table><thead><tr><th>目标时刻 · 北京时间</th><th>未来整点</th><th class="numeric">预测 PM₂.₅</th><th>80%名义区间</th><th class="numeric">持续基线</th><th>距实测起点</th><th>生成方式</th></tr></thead><tbody><tr v-for="p in forecast.points" :key="p.target"><td>{{ stamp(p.target) }}</td><td>第 {{ p.horizon }} 个</td><td class="numeric strong-value">{{ fmt(p.prediction) }}</td><td>{{ p.lower==null?'—':fmt(p.lower)+'—'+fmt(p.upper) }}</td><td class="numeric">{{ fmt(p.baseline) }}</td><td>+{{ p.lead_from_observation }} h</td><td><span class="live-method" :class="{extended:p.method==='recursive_extension'}">{{ p.method==='recursive_extension'?'递推延伸':'模型直出' }}</span></td></tr></tbody></table></div><div class="panel-note">目标时刻均在发布时间之后。{{ live.extension_hours?`实测存在延迟，最后 ${live.extension_hours} 个目标通过递推覆盖，误差可能更大。`:'本轮六个目标均由模型直接输出。' }}尚未发生的真实浓度保持未知。{{ live.interval_note }}<span v-if="live.nominal_coverage"> 历史测试显示，高浓度和浓度突变时区间覆盖不足，真实值仍可能超出范围。<a href="#online">查看分组检验</a></span></div><div v-if="live.nominal_coverage" class="live-risk"><label>关注参考线<input v-model.number="reference" type="number" min="1" max="1000" aria-label="PM2.5关注参考线" />μg/m³</label><p>{{ risk }}</p><small>用户自设分析参考线，非官方污染预警。</small></div></section>
        <div class="two-column-grid"><section class="panel"><div class="panel-heading"><div><div class="section-kicker">LATEST OBSERVATIONS</div><h2>最新站点实测</h2></div><span class="subtle-tag">点击可预测站点切换</span></div><Chart :option="mapOption" height="300px" label="北京最新实测站点PM2.5地图" @select="mapSelect" /><div class="panel-note">{{ stamp(live.origin) }} · 只显示该时刻有效实测。</div></section><section class="panel"><div class="panel-heading"><div><div class="section-kicker">PAST 72 HOURS</div><h2>模型使用的近期气象</h2></div><select v-model="weather" aria-label="实时历史气象变量" class="compact-select"><option v-for="(v,k) in wx" :value="k">{{ v[0] }}</option></select></div><Chart :option="weatherOption" height="300px" label="实时预测输入的过去72小时气象" /><div class="panel-note">同城共享的天气模型格点资料。{{ live.future_weather?'本模型训练与线上均使用GFS固定提前24小时预报。':'旧模型历史实验使用ERA5。' }}</div></section></div>
        <section class="panel"><div class="panel-heading"><div><div class="section-kicker">PUBLISHED WEATHER OUTLOOK</div><h2>同期天气展望</h2></div><span class="subtle-tag">Open-Meteo · 天气预报</span></div><div class="table-scroll"><table><thead><tr><th>时刻</th><th class="numeric">气温 °C</th><th class="numeric">湿度 %</th><th class="numeric">风速 m/s</th><th class="numeric">降水 mm</th></tr></thead><tbody><tr v-for="p in forecast.weather_next" :key="p.ts"><td>{{ stamp(p.ts) }}</td><td class="numeric">{{ fmt(p.temperature_2m) }}</td><td class="numeric">{{ fmt(p.relative_humidity_2m,0) }}</td><td class="numeric">{{ fmt(p.wind_speed_10m) }}</td><td class="numeric">{{ fmt(p.precipitation) }}</td></tr></tbody></table></div><div class="panel-note">{{ live.future_weather?'本表天气直接进入主模型；使用GFS固定提前24小时的预报，和训练口径一致。':'直接TCN读取过去72小时；未来天气用于展示及延迟递推。' }}未来污染物实测保持未知。</div></section>
      </template>
      <section class="panel"><div class="panel-heading"><div><div class="section-kicker">PROSPECTIVE VERIFICATION</div><h2>等待实测，积累在线误差</h2></div><span class="subtle-tag">已匹配 {{ fmt(live.online_evaluation?.matched,0) }} 条</span></div><p v-if="!live.online_evaluation?.matched" class="station-copy">已保存本次预测。后续实测到达后，系统才计算在线 MAE 和 RMSE；当前没有可报告的在线误差。</p><div v-else class="table-scroll"><table><thead><tr><th>未来小时</th><th class="numeric">已匹配站点预测</th><th class="numeric">TCN MAE</th><th class="numeric">TCN RMSE</th><th class="numeric">基线 RMSE</th></tr></thead><tbody><tr v-for="r in live.online_evaluation.by_horizon" :key="r.horizon"><td>{{ r.horizon }}</td><td class="numeric">{{ fmt(r.n,0) }}</td><td class="numeric">{{ fmt(r.mae,2) }}</td><td class="numeric">{{ fmt(r.rmse,2) }}</td><td class="numeric">{{ fmt(r.baseline_rmse,2) }}</td></tr></tbody></table></div><div class="panel-note">核验对象为站点预测；重复更新按站点、目标时刻和提前小时保留最新发布版本。<a href="#online">查看逐日、站点、浓度分组与区间覆盖 →</a></div></section>
      <section class="panel live-provenance"><div><div class="section-kicker">OBSERVATIONS → SPARK → CURRENT PREDICTION</div><h2>这次预测从哪里来</h2><p>空气实测与近几日记录进入 HDFS，由 Spark {{ live.spark_version }} 清洗、补齐小时网格并融合气象；{{ live.future_weather?'已训练TCN同时读取过去72小时与未来9小时天气，直接生成九个时长及分位区间。':'已训练TCN读取完整72小时序列。' }}</p><p>本次推理设备：{{ live.inference_device }} · {{ live.engine }}。本页会运行模型推理，更新数据不会重新训练。</p><div class="live-source-links"><a v-for="s in live.air_sources" :href="s.url" target="_blank" rel="noreferrer">{{ s.name }}<ArrowUpRight :size="12" /></a><a :href="live.weather_source.url" target="_blank" rel="noreferrer">气象接口说明<ArrowUpRight :size="12" /></a></div></div></section>
      <div class="method-note"><Info :size="16" /><p>{{ live.method_note }} {{ live.accuracy_note }}</p></div>
    </template>
  </template>
</template>
