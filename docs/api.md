# 后端接口约定

本文件用于后续界面重写。基础地址为 `http://localhost:8000`；参数均为查询参数，除刷新接口外均为 GET。

真实响应采集时间：`2026-10-23T00:11:43.978282+08:00`。POST 示例复用阶段1的真实请求日志，避免文档采集额外启动轮次。示例为响应节选，对象和数组有所截取；字段表给出完整已观察结构。

## 公共约定

- 历史时间是无时区的北京时间字符串；实时 ISO 时间带 `+08:00`。日期用 `YYYY-MM-DD`。
- PM2.5、PM10、SO2、NO2、O3 及浓度误差为 μg/m³；CO 为 mg/m³。气温 °C、湿度 %、气压 hPa、风速 m/s、风向 度、降水 mm。
- 数值 `null` 表示缺失、尚未收到实测或没有相应证据；页面应显示“暂无数据”。缺失标签不参与误差。
- `coverage` 在历史概览中是观测覆盖率，在预测评估中是区间实际覆盖率；都是0—1。`nominal_coverage` 是区间目标概率。
- `horizon` 在实时发布中相对发布时间整点，`lead_from_observation` 相对最近实测；因发布延迟两者可以不同。
- 业务错误一般为 `{"detail":"中文说明"}`。FastAPI 的类型、日期格式、范围和正则校验返回422及标准 `detail` 数组，其 `msg` 可能为英文。
- SQLite 历史库只读；在线核验按模型权重 SHA-256 分开，同一版本/站点/目标/提前小时取最后发布版。实时刷新是唯一主动更新入口。
- 字段路径中的 `[]` 表示数组元素，`*` 表示动态实验名或时长键。数组可为空；新增报告字段应同步更新本文件。

## 接口索引

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 返回应用标识及历史数据和模型的就绪状态。 |
| GET | `/api/meta` | 返回数据范围、模型和页面初始化需要的元信息。 |
| GET | `/api/overview` | 返回年度总体统计、城市地图摘要和已有分析结果。 |
| GET | `/api/snapshot` | 返回同一时刻的空间分布，保留各站点或城市的实测值。 |
| GET | `/api/trend` | 按选择的城市或站点返回指定年份的时间趋势。 |
| GET | `/api/pattern` | 返回按月份或小时聚合的污染变化规律。 |
| GET | `/api/weather` | 返回已对齐的污染和天气关联样本及相关性摘要。 |
| GET | `/api/models` | 读取已保存的模型登记和评估证据，不触发训练。 |
| GET | `/api/forecast` | 校验选择项后返回六小时预测及对应历史。 |
| GET | `/api/quality` | 返回原始缺失、冲突与清洗后有效数据统计。 |
| GET | `/api/export` | 按当前查询口径导出带中文编码标识的 CSV。 |
| GET | `/api/stations/meta` | 返回站点数据、下载和训练进度及页面选择范围。 |
| GET | `/api/stations/snapshot` | 返回同一时刻的空间分布，保留各站点或城市的实测值。 |
| GET | `/api/stations/history` | 读取指定站点的历史小时窗口，保留缺失和观测数量。 |
| GET | `/api/stations/trend` | 按选择的城市或站点返回指定年份的时间趋势。 |
| GET | `/api/stations/models` | 读取已保存的模型登记和评估证据，不触发训练。 |
| GET | `/api/stations/forecast` | 校验选择项后返回六小时预测及对应历史。 |
| GET | `/api/live/meta` | 返回数据范围、模型和页面初始化需要的元信息。 |
| GET | `/api/live/forecast` | 校验选择项后返回六小时预测及对应历史。 |
| POST | `/api/live/refresh` | 请求后台更新，复用并发保护和两分钟限频规则。 |
| GET | `/api/live/export` | 按当前查询口径导出带中文编码标识的 CSV。 |
| GET | `/api/live/evaluation` | 读取选定模型版本的在线核验结果。 |
| GET | `/api/live/evaluation/export` | 导出发布时已保存的预测、区间及后来到达的实测。 |
| GET | `/api/live/model` | 返回离线对比报告，省去逐秒 GPU 遥测以减小响应。 |
| GET | `/api/system` | 返回保存的 HDFS 清单、三代数据摘要、报告版本及本地产物信息。 |

## GET /api/health

无参数。此健康检查表示历史查询库是否存在，不代表所有实时来源均已就绪。

读取或写入：data/app/airquality.sqlite、data/app/forecasts.sqlite（存在性）。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `status` | string | 状态字符串；健康检查为 ok，盘点条目为 ok/error |
| `app_id` | string | 应用身份标识 |
| `data_ready` | boolean | 历史观测查询库是否存在 |
| `models_ready` | boolean | 预测库及相应模型登记是否就绪 |

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/health`，状态 `200`。

```json
{
  "status": "ok",
  "app_id": "beijing-pm25",
  "data_ready": true,
  "models_ready": true
}
```

## GET /api/meta

无参数。

读取或写入：config.json、models/registry.json、reports/data_summary.json、reports/training_progress.json。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `title` | string | 系统名称 |
| `cities` | array | 城市目录或城市 ID 列表，按实际结构读取 |
| `cities[]` | object | 城市目录或城市 ID 列表，按实际结构读取 |
| `cities[].id` | string | 城市 ID |
| `cities[].name` | string | 城市、站点、变量或来源的显示名称 |
| `cities[].latitude` | number | 纬度，度 |
| `cities[].longitude` | number | 经度，度 |
| `years` | array | 可选历史年份 |
| `years[]` | integer | 可选历史年份 |
| `date_range` | array | 起止日期，均包含 |
| `date_range[]` | string | 起止日期，均包含 |
| `default_origin` | string | 界面默认的历史预测起点，北京时间 |
| `forecast_range` | array | 历史回放起点的最小值与最大值 |
| `forecast_range[]` | string | 历史回放起点的最小值与最大值 |
| `summary` | object | 数据规模或误差的摘要对象 |
| `summary.spark_version` | string | 报告记录的 Spark 版本 |
| `summary.spark_master` | string | Spark 运行模式 |
| `summary.start_date` | string | 数据起始日期 |
| `summary.end_date` | string | 数据结束日期 |
| `summary.timezone` | string | 时间所属时区 |
| `summary.cities` | array | 城市目录或城市 ID 列表，按实际结构读取 |
| `summary.cities[]` | object | 城市目录或城市 ID 列表，按实际结构读取 |
| `summary.cities[].id` | string | 城市 ID |
| `summary.cities[].name` | string | 城市、站点、变量或来源的显示名称 |
| `summary.cities[].latitude` | number | 纬度，度 |
| `summary.cities[].longitude` | number | 经度，度 |
| `summary.panel_rows` | integer | 城市×小时完整网格行数 |
| `summary.distinct_city_hour_keys` | integer | 城市×小时唯一键数量 |
| `summary.beijing_feature_rows` | integer | 北京小时特征行数 |
| `summary.parquet_output` | string | 城市清洗结果 HDFS 目录 |
| `summary.beijing_valid_label_counts` | object | 各提前时长有效标签数量 |
| `summary.beijing_valid_label_counts.h1` | integer | 提前1小时的有效标签数 |
| `summary.beijing_valid_label_counts.h2` | integer | 提前2小时的有效标签数 |
| `summary.beijing_valid_label_counts.h3` | integer | 提前3小时的有效标签数 |
| `summary.beijing_valid_label_counts.h4` | integer | 提前4小时的有效标签数 |
| `summary.beijing_valid_label_counts.h5` | integer | 提前5小时的有效标签数 |
| `summary.beijing_valid_label_counts.h6` | integer | 提前6小时的有效标签数 |
| `summary.beijing_valid_label_counts.current_and_all_six_targets` | integer | 起点及全部六个标签都有效的小时数 |
| `summary.pm25_valid_hours_all_cities` | integer | 全部城市 PM2.5 有效小时数 |
| `summary.raw_bytes` | integer | 原始文件逻辑字节数，byte |
| `summary.source_missing_dates` | array | 原来源缺少的日期列表 |
| `summary.source_missing_dates[]` | string | 原来源缺少的日期列表 |
| `summary.download_summary` | object | 下载成功/缺失情况，按来源分组 |
| `summary.download_summary.air` | object | 空气质量来源摘要 |
| `summary.download_summary.air.missing` | integer | 缺失文件数量 |
| `summary.download_summary.air.ok` | integer | 成功文件数量 |
| `summary.download_summary.weather` | object | 天气来源或天气摘要 |
| `summary.download_summary.weather.ok` | integer | 成功文件数量 |
| `summary.units` | object | 字段单位映射 |
| `summary.units.pm25` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.pm10` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.so2` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.no2` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.o3` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.co` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.temperature_2m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.surface_pressure` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.relative_humidity_2m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.wind_speed_10m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.wind_direction_10m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.precipitation` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.notes` | array | 方法和数据边界说明列表 |
| `summary.notes[]` | string | 方法和数据边界说明列表 |
| `models_ready` | boolean | 预测库及相应模型登记是否就绪 |
| `training` | object | 已保存的训练进度 |
| `training.status` | string | 状态字符串；健康检查为 ok，盘点条目为 ok/error |
| `training.current` | string | 预测起点的 PM2.5，μg/m³ |
| `training.completed` | integer | 已完成任务数或整体完成布尔值，按类型区分 |
| `training.total` | integer | 进度计划中的总任务数 |
| `training.elapsed_seconds` | integer | 运行总耗时，秒 |
| `recommended` | object | 按提前时长选择的推荐模型映射 |
| `recommended.*` | string | 提前小时字符串对应的推荐模型标识 |
| `weather_note` | string | 天气来源、可用性或历史与实时差异的说明 |

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/meta`，状态 `200`。

```json
{
  "title": "北京市 PM₂.₅ 时空分析与短时预测系统",
  "cities": [
    {
      "id": "beijing",
      "name": "北京",
      "latitude": 39.9042,
      "longitude": 116.4074
    }
  ],
  "years": [
    2015
  ],
  "date_range": [
    "2015-01-01"
  ],
  "default_origin": "2025-12-30 12:00:00",
  "forecast_range": [
    "2024-01-01T00:00"
  ],
  "summary": {
    "spark_version": "3.5.8",
    "spark_master": "local[4]",
    "start_date": "2015-01-01",
    "end_date": "2025-12-31"
  }
}
```

## GET /api/overview

year 为 2015—2025 的字符串或 all。

读取或写入：data/app/airquality.sqlite 的 daily；reports/yearly_city_quality.csv、reports/analysis.json。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `year` | string | `2025` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `year` | string | 公历年份 |
| `beijing_mean` | number | 选定年份北京 PM2.5 加权均值，μg/m³ |
| `beijing_max` | number | 北京 PM2.5 最大小时值，μg/m³ |
| `coverage` | number | PM2.5有效观测占预期小时的比例，0—1 |
| `yoy_percent` | number | 北京均值相对上一年的变化百分数，% |
| `city_count` | integer | 城市数量 |
| `quality` | array | 所选城市年度数据质量列表 |
| `quality[]` | object | 所选城市年度数据质量列表 |
| `quality[].year` | number | 公历年份 |
| `quality[].city_id` | string | 城市 ID |
| `quality[].city_name` | string | 城市中文名 |
| `quality[].expected_hours` | number | 预期完整小时数 |
| `quality[].pm25_valid_hours` | number | PM2.5 有效观测小时数 |
| `quality[].air_source_hours` | number | 原始空气质量记录覆盖的小时数 |
| `quality[].weather_hours` | number | 有天气来源记录的小时数 |
| `quality[].pm25_mean` | number | PM2.5 平均值，μg/m³ |
| `quality[].pm25_min` | number | PM2.5 最小值，μg/m³ |
| `quality[].pm25_max` | number | PM2.5 最大值，μg/m³ |
| `quality[].invalid_air_values` | number | 清洗发现的非法空气质量数值数 |
| `quality[].conflicting_air_values` | number | 同键同污染物相互冲突的数值数 |
| `quality[].temperature_2m_valid_hours` | number | 城市代表点气温，°C对应的有效小时数 |
| `quality[].relative_humidity_2m_valid_hours` | number | 相对湿度，%对应的有效小时数 |
| `quality[].surface_pressure_valid_hours` | number | 地面气压，hPa对应的有效小时数 |
| `quality[].wind_speed_10m_valid_hours` | number | 风速，m/s对应的有效小时数 |
| `quality[].wind_direction_10m_valid_hours` | number | 风向，度对应的有效小时数 |
| `quality[].precipitation_valid_hours` | number | 降水量，mm对应的有效小时数 |
| `quality[].pm25_missing_ratio` | number | PM2.5 缺失比例，0—1 |
| `analysis` | object | 已生成的相关性等分析结果 |
| `analysis.city_correlations` | array | 城市 PM2.5 之间的相关系数或成对统计 |
| `analysis.city_correlations[]` | object | 城市 PM2.5 之间的相关系数或成对统计 |
| `analysis.city_correlations[].city` | string | 所选城市 ID，或系统证据中的城市代摘要 |
| `analysis.city_correlations[].other` | string | 城市相关性统计中的对方城市 ID |
| `analysis.city_correlations[].correlation` | number | Pearson 相关系数，-1—1；无法计算时为 null |
| `analysis.city_correlations[].n` | integer | 参与当前统计的有效样本数 |
| `analysis.beijing_weather_correlations` | object | 北京 PM2.5 与天气变量的 Pearson 相关系数 |
| `analysis.beijing_weather_correlations.temperature_2m` | number | 城市代表点气温，°C |
| `analysis.beijing_weather_correlations.relative_humidity_2m` | number | 相对湿度，% |
| `analysis.beijing_weather_correlations.surface_pressure` | number | 地面气压，hPa |
| `analysis.beijing_weather_correlations.wind_speed_10m` | number | 风速，m/s |
| `analysis.beijing_weather_correlations.wind_direction_10m` | number | 风向，度 |
| `analysis.beijing_weather_correlations.precipitation` | number | 降水量，mm |
| `analysis.note` | string | 统计、来源或使用边界的文字说明 |

### 错误与状态

- `422`：年份应为 2015—2025 或 all。
- `503`：数据仍在准备，请稍后重试。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/overview`，状态 `200`。

```json
{
  "year": "2025",
  "beijing_mean": 27.264462809917354,
  "beijing_max": 202.0,
  "coverage": 0.9668949771689498,
  "yoy_percent": -13.114273255499109,
  "city_count": 6,
  "quality": [
    {
      "year": 2025.0,
      "city_id": "baoding",
      "city_name": "保定",
      "expected_hours": 8760.0
    }
  ]
}
```

## GET /api/snapshot

time 为无时区的北京时间整点，2015-01-01 至 2025-12-31。

读取或写入：data/app/airquality.sqlite 的 hourly。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `time` | string | `2025-12-30T12:00` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `time` | string | 已规范化的历史北京时间或聚合时间标签 |
| `cities` | array | 城市目录或城市 ID 列表，按实际结构读取 |
| `cities[]` | object | 城市目录或城市 ID 列表，按实际结构读取 |
| `cities[].city_id` | string | 城市 ID |
| `cities[].ts` | string | 小时记录的北京时间 |
| `cities[].pm25` | number | 小时 PM2.5 浓度，μg/m³ |
| `cities[].pm10` | number | 小时 PM10 浓度，μg/m³ |
| `cities[].so2` | number | 小时 SO2 浓度，μg/m³ |
| `cities[].no2` | number | 小时 NO2 浓度，μg/m³ |
| `cities[].o3` | number | 小时 O3 浓度，μg/m³ |
| `cities[].co` | number | 小时 CO 浓度，mg/m³ |
| `cities[].aqi` | number | 源文件中的空气质量指数，无量纲 |
| `cities[].temperature_2m` | number | 城市代表点气温，°C |
| `cities[].relative_humidity_2m` | number | 相对湿度，% |
| `cities[].surface_pressure` | number | 地面气压，hPa |
| `cities[].wind_speed_10m` | number | 风速，m/s |
| `cities[].wind_direction_10m` | number | 风向，度 |
| `cities[].precipitation` | number | 降水量，mm |

### 错误与状态

- `422`：请选择 2015—2025 年内的整点，北京时间。
- `503`：数据仍在准备，请稍后重试。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/snapshot`，状态 `200`。

```json
{
  "time": "2025-12-30 12:00:00",
  "cities": [
    {
      "city_id": "baoding",
      "ts": "2025-12-30 12:00:00",
      "pm25": 20.0,
      "pm10": 54.0
    }
  ]
}
```

## GET /api/trend

cities 为配置中的城市 ID，以逗号分隔并去重；start/end 为历史范围内的日期且 start≤end。resolution=auto 时日期差≤7用 hour、≤400用 day，否则 month；手动 hour 时日期差不得超过92天。起止日期均包含。

读取或写入：data/app/airquality.sqlite 的 hourly / daily。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `cities` | string | `beijing` |
| `start` | string | `2015-01-01` |
| `end` | string | `2025-12-31` |
| `resolution` | string | `auto` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `resolution` | string | 实际返回的聚合粒度：hour/day/month |
| `start` | string | 起始日期或时间（上下文决定） |
| `end` | string | 结束日期或时间（上下文决定） |
| `series` | array | 按城市组织的曲线列表 |
| `series[]` | object | 按城市组织的曲线列表 |
| `series[].city_id` | string | 城市 ID |
| `series[].name` | string | 城市、站点、变量或来源的显示名称 |
| `series[].points` | array | 按时间或提前时长排列的数据点列表 |
| `series[].points[]` | object | 按时间或提前时长排列的数据点列表 |
| `series[].points[].city_id` | string | 城市 ID |
| `series[].points[].time` | string | 已规范化的历史北京时间或聚合时间标签 |
| `series[].points[].value` | number | 图表所用的聚合浓度或统计值 |
| `series[].points[].n` | integer | 参与当前统计的有效样本数 |

### 错误与状态

- `422`：城市参数无效。
- `422`：小时曲线最多展示 93 天，请改用日或月均值。
- `422`：日期范围无效，请选择 2015—2025 年内的起止日期。
- `422`：时间粒度无效。
- `503`：数据仍在准备，请稍后重试。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/trend`，状态 `200`。

```json
{
  "resolution": "month",
  "start": "2015-01-01",
  "end": "2025-12-31",
  "series": [
    {
      "city_id": "beijing",
      "name": "北京",
      "points": [
        {
          "city_id": "beijing",
          "time": "2015-01",
          "value": 98.02083333333333,
          "n": 672
        }
      ]
    }
  ]
}
```

## GET /api/pattern

city 为配置中的城市 ID；year 为 2015—2025 或 all。

读取或写入：data/app/airquality.sqlite 的 hourly_pattern / seasonal。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `city` | string | `beijing` |
| `year` | string | `2025` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `city` | string | 所选城市 ID，或系统证据中的城市代摘要 |
| `year` | string | 公历年份 |
| `cells` | array | 月份×小时的聚合网格 |
| `cells[]` | object | 月份×小时的聚合网格 |
| `cells[].month` | integer | 月份，1—12 |
| `cells[].hour` | integer | 小时，0—23 |
| `cells[].value` | number | 图表所用的聚合浓度或统计值 |
| `cells[].n` | integer | 参与当前统计的有效样本数 |
| `seasons` | array | 季节聚合统计 |
| `seasons[]` | object | 季节聚合统计 |
| `seasons[].season` | string | 季节标签 |
| `seasons[].value` | number | 图表所用的聚合浓度或统计值 |
| `seasons[].n` | integer | 参与当前统计的有效样本数 |

### 错误与状态

- `422`：城市参数无效。
- `422`：年份应为 2015—2025 或 all。
- `503`：数据仍在准备，请稍后重试。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/pattern`，状态 `200`。

```json
{
  "city": "beijing",
  "year": "2025",
  "cells": [
    {
      "month": 1,
      "hour": 0,
      "value": 32.774193548387096,
      "n": 31
    }
  ],
  "seasons": [
    {
      "season": "冬季",
      "value": 28.5625,
      "n": 2096
    }
  ]
}
```

## GET /api/weather

city/year 同上；variable 仅 temperature_2m、relative_humidity_2m、wind_speed_10m、surface_pressure、precipitation。相关性使用全部成对有效小时，散点按步长抽样。

读取或写入：data/app/airquality.sqlite 的 hourly。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `city` | string | `beijing` |
| `year` | string | `2025` |
| `variable` | string | `relative_humidity_2m` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `variable` | string | 所选天气变量字段名 |
| `name` | string | 城市、站点、变量或来源的显示名称 |
| `correlation` | number | Pearson 相关系数，-1—1；无法计算时为 null |
| `n` | integer | 参与当前统计的有效样本数 |
| `points` | array | 按时间或提前时长排列的数据点列表 |
| `points[]` | object | 按时间或提前时长排列的数据点列表 |
| `points[].ts` | string | 小时记录的北京时间 |
| `points[].x` | number | 天气散点的横轴值，单位由 variable 决定 |
| `points[].y` | number | 天气散点的 PM2.5 纵轴值，μg/m³ |

### 错误与状态

- `422`：城市参数无效。
- `422`：年份应为 2015—2025 或 all。
- `422`：气象变量无效。
- `503`：数据仍在准备，请稍后重试。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/weather`，状态 `200`。

```json
{
  "variable": "relative_humidity_2m",
  "name": "相对湿度",
  "correlation": 0.23285263549318827,
  "n": 8470,
  "points": [
    {
      "ts": "2025-01-01 00:00:00",
      "x": 61.0,
      "y": 35.0
    }
  ]
}
```

## GET /api/models

无参数。runs 的键为 特征组:模型:h时长；recommended_by_horizon 按验证集选择。

读取或写入：models/registry.json、reports/training_progress.json。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `registry` | object | 已保存的模型登记表 |
| `registry.schema_version` | integer | 原模型登记格式版本 |
| `registry.engine` | string | 实际推理框架及版本 |
| `registry.target` | string | 预测目标时刻，北京时间 |
| `registry.method` | string | direct 为直接输出，recursive_extension 为旧版尾部递推 |
| `registry.train_period` | string | 训练时间段 |
| `registry.validation_period` | string | 验证时间段 |
| `registry.test_period` | string | 测试时间段 |
| `registry.weather` | string | 天气来源或天气摘要 |
| `registry.runs` | object | 各实验的模型参数和评估，动态键见本节约定 |
| `registry.runs.*` | object | 动态实验键对应的模型记录，结构与同级其他实验一致 |
| `registry.runs.*.model` | string | 模型标识或所选模型 |
| `registry.runs.*.variant` | string | 特征或模型消融组标识 |
| `registry.runs.*.horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `registry.runs.*.metrics` | array | 训练/验证/测试的误差指标 |
| `registry.runs.*.metrics[]` | object | 训练/验证/测试的误差指标 |
| `registry.runs.*.metrics[].split` | string | 样本所属划分，如 validation/test |
| `registry.runs.*.metrics[].n` | integer | 参与当前统计的有效样本数 |
| `registry.runs.*.metrics[].mae` | number | 平均绝对误差，μg/m³ |
| `registry.runs.*.metrics[].rmse` | number | 均方根误差，μg/m³ |
| `registry.runs.*.metrics[].r2` | number | 决定系数，无量纲 |
| `registry.runs.*.feature_count` | integer | 输入特征数量 |
| `registry.runs.*.train_rows` | integer | 训练有效样本行数 |
| `registry.runs.*.features` | array | 输入特征名列表或特征统计对象 |
| `registry.runs.*.features[]` | string | 输入特征名列表或特征统计对象 |
| `registry.runs.*.model_path` | string | 已保存模型的位置 |
| `registry.runs.*.fit_seconds` | number | 模型拟合耗时，秒 |
| `registry.runs.*.feature_importance` | array | 树模型的特征重要性列表 |
| `registry.runs.*.feature_importance[]` | object | 树模型的特征重要性列表 |
| `registry.runs.*.feature_importance[].feature` | string | 特征名 |
| `registry.runs.*.feature_importance[].importance` | number | 特征重要性，无量纲 |
| `registry.runs.*.parameters` | object | 原模型训练参数快照 |
| `registry.runs.*.parameters.bootstrap` | string | 树训练是否有放回采样 |
| `registry.runs.*.parameters.cacheNodeIds` | string | 是否缓存树节点编号 |
| `registry.runs.*.parameters.checkpointInterval` | string | 模型训练检查点间隔 |
| `registry.runs.*.parameters.featureSubsetStrategy` | string | 每次树分裂的候选特征策略 |
| `registry.runs.*.parameters.featuresCol` | string | 向量特征列名 |
| `registry.runs.*.parameters.impurity` | string | 树节点不纯度度量 |
| `registry.runs.*.parameters.labelCol` | string | 标签列名 |
| `registry.runs.*.parameters.leafCol` | string | 可选叶节点输出列名 |
| `registry.runs.*.parameters.maxBins` | string | 连续特征分箱上限 |
| `registry.runs.*.parameters.maxDepth` | string | 树最大深度 |
| `registry.runs.*.parameters.maxMemoryInMB` | string | 树训练直方图等的内存预算，MB |
| `registry.runs.*.parameters.minInfoGain` | string | 树分裂的最小信息增益 |
| `registry.runs.*.parameters.minInstancesPerNode` | string | 叶节点最少样本数 |
| `registry.runs.*.parameters.minWeightFractionPerNode` | string | 节点最小样本权重占比 |
| `registry.runs.*.parameters.numTrees` | string | 随机森林树数量 |
| `registry.runs.*.parameters.predictionCol` | string | 预测输出列名 |
| `registry.runs.*.parameters.seed` | string | 固定随机种子 |
| `registry.runs.*.parameters.subsamplingRate` | string | 训练子采样比例，0—1 |
| `registry.runs.*.parameters.lossType` | string | 梯度提升损失类型 |
| `registry.runs.*.parameters.maxIter` | string | 梯度提升迭代次数 |
| `registry.runs.*.parameters.stepSize` | string | 梯度提升学习步长 |
| `registry.runs.*.parameters.validationTol` | string | 梯度提升验证停止阈值 |
| `registry.selection_rule` | string | 推荐模型的选择规则说明 |
| `registry.updated_at_utc` | string | 原报告进度更新时间，UTC |
| `registry.recommended_by_horizon` | object | 按验证误差选择的推荐模型，键为提前小时字符串 |
| `registry.recommended_by_horizon.*` | string | 提前小时字符串对应的推荐模型标识 |
| `registry.completed` | boolean | 已完成任务数或整体完成布尔值，按类型区分 |
| `progress` | object | 已保存的训练进度对象 |
| `progress.status` | string | 状态字符串；健康检查为 ok，盘点条目为 ok/error |
| `progress.current` | string | 预测起点的 PM2.5，μg/m³ |
| `progress.completed` | integer | 已完成任务数或整体完成布尔值，按类型区分 |
| `progress.total` | integer | 进度计划中的总任务数 |
| `progress.elapsed_seconds` | integer | 运行总耗时，秒 |

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/models`，状态 `200`。

```json
{
  "registry": {
    "schema_version": 1,
    "engine": "Spark ML 3.5.8",
    "target": "Beijing city mean PM2.5 (ug/m3)",
    "method": "Residual regression: predicted change + observed current PM2.5, clipped at zero"
  },
  "progress": {
    "status": "complete",
    "current": "complete",
    "completed": 24,
    "total": 24
  }
}
```

## GET /api/forecast

origin 为无时区的北京时间整点，2024-01-01T00:00 至 2025-12-31T17:00；model 为 best、persistence、rf、gbt。仅查询历史缓存；缺少完整预测时返回错误。

读取或写入：data/app/forecasts.sqlite、data/app/airquality.sqlite、models/registry.json。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `origin` | string | `2025-12-30T12:00` |
| `model` | string | `best` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `origin` | string | 最后可用实测的预测起点，北京时间 |
| `model` | string | 模型标识或所选模型 |
| `split` | string | 样本所属划分，如 validation/test |
| `points` | array | 按时间或提前时长排列的数据点列表 |
| `points[]` | object | 按时间或提前时长排列的数据点列表 |
| `points[].model` | string | 模型标识或所选模型 |
| `points[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `points[].origin` | string | 最后可用实测的预测起点，北京时间 |
| `points[].target` | string | 预测目标时刻，北京时间 |
| `points[].prediction` | number | 模型预测 PM2.5；v3 为中位数，μg/m³ |
| `points[].actual` | null/number | 目标时刻实测 PM2.5，未到达为 null，μg/m³ |
| `points[].baseline` | number | 起点 PM2.5 不变的持续性预测，μg/m³ |
| `history` | array | 过去污染与天气小时序列 |
| `history[]` | object | 过去污染与天气小时序列 |
| `history[].ts` | string | 小时记录的北京时间 |
| `history[].pm25` | null/number | 小时 PM2.5 浓度，μg/m³ |
| `current` | number | 预测起点的 PM2.5，μg/m³ |
| `window_mae` | number | 当前历史回放窗口内已有实测目标的 MAE，μg/m³ |
| `actual_points` | integer | 当前回放窗口有效实测目标数 |
| `weather_note` | string | 天气来源、可用性或历史与实时差异的说明 |

### 错误与状态

- `404`：该时刻北京 PM₂.₅ 观测缺失，无法构建预测，请选择相邻时刻。
- `404`：该时点预测数据不完整，请选择其他时刻。
- `422`：模型参数无效。
- `422`：请选择 2015—2025 年内的整点，北京时间。
- `422`：预测回放支持 2024—2025 年，最晚起点为 2025-12-31 17:00。
- `503`：数据仍在准备，请稍后重试。
- `503`：模型预测索引正在更新，请稍后重试。
- `503`：预测模型正在训练，请稍后重试。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/forecast`，状态 `200`。

```json
{
  "origin": "2025-12-30 12:00:00",
  "model": "best",
  "split": "test",
  "points": [
    {
      "model": "rf",
      "horizon": 1,
      "origin": "2025-12-30 12:00:00",
      "target": "2025-12-30 13:00:00"
    }
  ],
  "history": [
    {
      "ts": "2025-12-28 13:00:00",
      "pm25": 79.0
    }
  ],
  "current": 6.0,
  "window_mae": 3.0239493655554077
}
```

## GET /api/quality

无参数。verification 中的旧测试计数是原清洗核验记录，不是当前全量测试数。

读取或写入：reports/yearly_city_quality.csv、reports/data_summary.json、reports/verification.json。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `rows` | array | 质量统计行列表 |
| `rows[]` | object | 质量统计行列表 |
| `rows[].year` | number | 公历年份 |
| `rows[].city_id` | string | 城市 ID |
| `rows[].city_name` | string | 城市中文名 |
| `rows[].expected_hours` | number | 预期完整小时数 |
| `rows[].pm25_valid_hours` | number | PM2.5 有效观测小时数 |
| `rows[].air_source_hours` | number | 原始空气质量记录覆盖的小时数 |
| `rows[].weather_hours` | number | 有天气来源记录的小时数 |
| `rows[].pm25_mean` | number | PM2.5 平均值，μg/m³ |
| `rows[].pm25_min` | number | PM2.5 最小值，μg/m³ |
| `rows[].pm25_max` | number | PM2.5 最大值，μg/m³ |
| `rows[].invalid_air_values` | number | 清洗发现的非法空气质量数值数 |
| `rows[].conflicting_air_values` | number | 同键同污染物相互冲突的数值数 |
| `rows[].temperature_2m_valid_hours` | number | 城市代表点气温，°C对应的有效小时数 |
| `rows[].relative_humidity_2m_valid_hours` | number | 相对湿度，%对应的有效小时数 |
| `rows[].surface_pressure_valid_hours` | number | 地面气压，hPa对应的有效小时数 |
| `rows[].wind_speed_10m_valid_hours` | number | 风速，m/s对应的有效小时数 |
| `rows[].wind_direction_10m_valid_hours` | number | 风向，度对应的有效小时数 |
| `rows[].precipitation_valid_hours` | number | 降水量，mm对应的有效小时数 |
| `rows[].pm25_missing_ratio` | number | PM2.5 缺失比例，0—1 |
| `summary` | object | 数据规模或误差的摘要对象 |
| `summary.spark_version` | string | 报告记录的 Spark 版本 |
| `summary.spark_master` | string | Spark 运行模式 |
| `summary.start_date` | string | 数据起始日期 |
| `summary.end_date` | string | 数据结束日期 |
| `summary.timezone` | string | 时间所属时区 |
| `summary.cities` | array | 城市目录或城市 ID 列表，按实际结构读取 |
| `summary.cities[]` | object | 城市目录或城市 ID 列表，按实际结构读取 |
| `summary.cities[].id` | string | 城市 ID |
| `summary.cities[].name` | string | 城市、站点、变量或来源的显示名称 |
| `summary.cities[].latitude` | number | 纬度，度 |
| `summary.cities[].longitude` | number | 经度，度 |
| `summary.panel_rows` | integer | 城市×小时完整网格行数 |
| `summary.distinct_city_hour_keys` | integer | 城市×小时唯一键数量 |
| `summary.beijing_feature_rows` | integer | 北京小时特征行数 |
| `summary.parquet_output` | string | 城市清洗结果 HDFS 目录 |
| `summary.beijing_valid_label_counts` | object | 各提前时长有效标签数量 |
| `summary.beijing_valid_label_counts.h1` | integer | 提前1小时的有效标签数 |
| `summary.beijing_valid_label_counts.h2` | integer | 提前2小时的有效标签数 |
| `summary.beijing_valid_label_counts.h3` | integer | 提前3小时的有效标签数 |
| `summary.beijing_valid_label_counts.h4` | integer | 提前4小时的有效标签数 |
| `summary.beijing_valid_label_counts.h5` | integer | 提前5小时的有效标签数 |
| `summary.beijing_valid_label_counts.h6` | integer | 提前6小时的有效标签数 |
| `summary.beijing_valid_label_counts.current_and_all_six_targets` | integer | 起点及全部六个标签都有效的小时数 |
| `summary.pm25_valid_hours_all_cities` | integer | 全部城市 PM2.5 有效小时数 |
| `summary.raw_bytes` | integer | 原始文件逻辑字节数，byte |
| `summary.source_missing_dates` | array | 原来源缺少的日期列表 |
| `summary.source_missing_dates[]` | string | 原来源缺少的日期列表 |
| `summary.download_summary` | object | 下载成功/缺失情况，按来源分组 |
| `summary.download_summary.air` | object | 空气质量来源摘要 |
| `summary.download_summary.air.missing` | integer | 缺失文件数量 |
| `summary.download_summary.air.ok` | integer | 成功文件数量 |
| `summary.download_summary.weather` | object | 天气来源或天气摘要 |
| `summary.download_summary.weather.ok` | integer | 成功文件数量 |
| `summary.units` | object | 字段单位映射 |
| `summary.units.pm25` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.pm10` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.so2` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.no2` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.o3` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.co` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.temperature_2m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.surface_pressure` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.relative_humidity_2m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.wind_speed_10m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.wind_direction_10m` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.units.precipitation` | string | 该字段的单位字符串；对应物理量见公共单位约定 |
| `summary.notes` | array | 方法和数据边界说明列表 |
| `summary.notes[]` | string | 方法和数据边界说明列表 |
| `verification` | object | 已保存的数据核验记录 |
| `verification.local_parquet_readback` | string | 原清洗 Parquet 回读核验状态 |
| `verification.panel` | object | 城市网格核验摘要 |
| `verification.panel.rows` | integer | 质量统计行列表 |
| `verification.panel.valid_pm25` | integer | 有效 PM2.5 观测数 |
| `verification.features` | object | 输入特征名列表或特征统计对象 |
| `verification.features.rows` | integer | 质量统计行列表 |
| `verification.features.valid_h6` | integer | 有效六小时标签数 |
| `verification.source_cell_and_target_checks` | integer | 原始单元格与目标标签的核对次数 |
| `verification.unit_tests_passed` | integer | 原报告生成时通过的测试数量 |

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/quality`，状态 `200`。

```json
{
  "rows": [
    {
      "year": 2015.0,
      "city_id": "baoding",
      "city_name": "保定",
      "expected_hours": 8760.0
    }
  ],
  "summary": {
    "spark_version": "3.5.8",
    "spark_master": "local[4]",
    "start_date": "2015-01-01",
    "end_date": "2025-12-31"
  },
  "verification": {
    "local_parquet_readback": "passed",
    "panel": {
      "rows": 578592,
      "valid_pm25": 564028
    },
    "features": {
      "rows": 96432,
      "valid_h6": 93877
    },
    "source_cell_and_target_checks": 48
  }
}
```

## GET /api/export

city 为有效城市；日期范围在2015—2025年内，日期差≤366天（含首尾最多367个自然日）；起止均包含。

读取或写入：data/app/airquality.sqlite 的 hourly。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `city` | string | `beijing` |
| `start` | string | `2025-01-01` |
| `end` | string | `2025-12-31` |

### 返回字段

CSV列顺序：北京时间（小时）、城市（中文名）、PM2.5(ug/m3)、PM10(ug/m3)、气温(C)、相对湿度(%)、风速(m/s)。
编码 UTF-8 BOM；Content-Type 为 text/csv；Content-Disposition 为 attachment。

### 错误与状态

- `422`：单次导出最多 367 天，请分年导出。
- `422`：城市参数无效。
- `422`：日期范围无效，请选择 2015—2025 年内的起止日期。
- `503`：数据仍在准备，请稍后重试。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/export?start=2025-01-01&end=2025-01-01`，状态 `200`。

```csv
北京时间,城市,PM2.5(ug/m3),PM10(ug/m3),气温(C),相对湿度(%),风速(m/s)
2025-01-01 00:00:00,北京,35.0,78.0,-4.5,61.0,1.82
2025-01-01 01:00:00,北京,33.0,71.0,-5.1,64.0,1.75
```

## GET /api/stations/meta

无参数；ready=false 时 stations 为空数组。

读取或写入：data/app/stations.sqlite、models/station_registry.json、reports/station_summary.json、station_download_progress.json、station_training_progress.json、station_cuda_progress.json。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `ready` | boolean | 相应模块已有可读取的产物；实时预测还应检查 usable |
| `summary` | object | 数据规模或误差的摘要对象 |
| `summary.grid_hours` | integer | 站点×小时完整网格行数 |
| `summary.valid_pm25` | integer | 有效 PM2.5 观测数 |
| `summary.stations` | integer | 站点目录或站点数量，按类型区分 |
| `summary.start` | string | 起始日期或时间（上下文决定） |
| `summary.end` | string | 结束日期或时间（上下文决定） |
| `summary.source_days` | integer | 实际有原始档案的日期数 |
| `summary.expected_days` | integer | 预期日期总数 |
| `summary.feature_count` | integer | 输入特征数量 |
| `summary.weather_history_hours` | integer | 过去天气窗口长度，小时 |
| `summary.hdfs` | string | 相关数据在 HDFS 中的路径 |
| `summary.spark_version` | string | 报告记录的 Spark 版本 |
| `summary.weather_note` | string | 天气来源、可用性或历史与实时差异的说明 |
| `summary.status` | string | 状态字符串；健康检查为 ok，盘点条目为 ok/error |
| `summary.stations_metadata` | array | 训练所用站点元数据列表 |
| `summary.stations_metadata[]` | object | 训练所用站点元数据列表 |
| `summary.stations_metadata[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `summary.stations_metadata[].city_id` | string | 城市 ID |
| `summary.stations_metadata[].city_name` | string | 城市中文名 |
| `summary.stations_metadata[].name` | string | 城市、站点、变量或来源的显示名称 |
| `summary.stations_metadata[].latitude` | number | 纬度，度 |
| `summary.stations_metadata[].longitude` | number | 经度，度 |
| `summary.sequence_columns` | array | 历史输入通道的有序字段列表 |
| `summary.sequence_columns[]` | string | 历史输入通道的有序字段列表 |
| `summary.splits` | object | 按时间划分的训练、选择、校准和测试边界 |
| `summary.splits.train_end` | integer | 训练期最后年份 |
| `summary.splits.validation` | integer | 验证期或验证指标 |
| `summary.splits.test` | integer | 测试期或测试指标 |
| `summary.source_format` | string | 原始来源格式 |
| `summary.sequence_parquet` | string | 已生成序列 Parquet 的位置 |
| `summary.raw_archive_bytes` | integer | 站点全国原始档案字节数，byte |
| `summary.source_file_count` | integer | 全国档案原始文件数 |
| `summary.archive_commit` | string | 公开档案固定提交哈希 |
| `summary.archive_repository` | string | 公开档案仓库地址 |
| `summary.web_database_bytes` | integer | 发布的站点 SQLite 字节数，byte |
| `summary.indexed_predictions` | object | 已导入查询库的各模型/提前时长预测行数 |
| `summary.indexed_predictions.*` | integer | 对应模型及提前小时已入库的预测行数 |
| `download` | object | 已保存的站点下载进度 |
| `download.repository` | string | 来源仓库地址 |
| `download.commit` | string | 来源提交哈希 |
| `download.hourly_files` | integer | 已取得的原始小时文件数 |
| `download.raw_bytes` | integer | 原始文件逻辑字节数，byte |
| `download.start` | string | 起始日期或时间（上下文决定） |
| `download.end` | string | 结束日期或时间（上下文决定） |
| `download.status` | string | 状态字符串；健康检查为 ok，盘点条目为 ok/error |
| `training` | object | 已保存的训练进度 |
| `training.phase` | string | 当前流水线阶段标识 |
| `training.completed` | integer | 已完成任务数或整体完成布尔值，按类型区分 |
| `gpu_training` | object | 已保存的 CUDA 训练进度 |
| `gpu_training.phase` | string | 当前流水线阶段标识 |
| `gpu_training.completed` | integer | 已完成任务数或整体完成布尔值，按类型区分 |
| `gpu_training.device` | string | 报告记录的执行设备名称 |
| `gpu_training.best_epoch` | integer | 按模型选择期指标选出的轮次 |
| `stations` | array | 站点目录或站点数量，按类型区分 |
| `stations[]` | object | 站点目录或站点数量，按类型区分 |
| `stations[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `stations[].name` | string | 城市、站点、变量或来源的显示名称 |
| `stations[].city_id` | string | 城市 ID |
| `stations[].city_name` | string | 城市中文名 |
| `stations[].latitude` | number | 纬度，度 |
| `stations[].longitude` | number | 经度，度 |
| `default_origin` | string | 界面默认的历史预测起点，北京时间 |
| `forecast_range` | array | 历史回放起点的最小值与最大值 |
| `forecast_range[]` | string | 历史回放起点的最小值与最大值 |

### 错误与状态

- `503`：站点数据与 CUDA 模型正在准备。

### 实际响应节选

请求：`GET /api/stations/meta`，状态 `200`。

```json
{
  "ready": true,
  "summary": {
    "grid_hours": 2840184,
    "valid_pm25": 2503919,
    "stations": 81,
    "start": "2022-01-01"
  },
  "download": {
    "repository": "https://github.com/HeQinWill/CNEMC",
    "commit": "6853cea3099c222a0da078b22f5dcb534bf36112",
    "hourly_files": 34580,
    "raw_bytes": 11205092271
  },
  "training": {
    "phase": "complete",
    "completed": 19
  },
  "gpu_training": {
    "phase": "complete",
    "completed": 6,
    "device": "NVIDIA GeForce RTX 4080 Laptop GPU",
    "best_epoch": 6
  },
  "stations": [
    {
      "station_id": "1051A",
      "name": "游泳馆",
      "city_id": "baoding",
      "city_name": "保定"
    }
  ],
  "default_origin": "2025-12-30T12:00"
}
```

## GET /api/stations/snapshot

time 为2022—2025年的北京时间整点；city 为六个城市 ID 或 all。

读取或写入：data/app/stations.sqlite 的 stations / hourly。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `time` | string | `2025-12-30T12:00` |
| `city` | string | `beijing` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `time` | string | 已规范化的历史北京时间或聚合时间标签 |
| `stations` | array | 站点目录或站点数量，按类型区分 |
| `stations[]` | object | 站点目录或站点数量，按类型区分 |
| `stations[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `stations[].name` | string | 城市、站点、变量或来源的显示名称 |
| `stations[].city_id` | string | 城市 ID |
| `stations[].ts` | string | 小时记录的北京时间 |
| `stations[].pm25` | null/number | 小时 PM2.5 浓度，μg/m³ |
| `stations[].pm10` | null/number | 小时 PM10 浓度，μg/m³ |
| `stations[].so2` | null/number | 小时 SO2 浓度，μg/m³ |
| `stations[].no2` | null/number | 小时 NO2 浓度，μg/m³ |
| `stations[].o3` | null/number | 小时 O3 浓度，μg/m³ |
| `stations[].co` | null/number | 小时 CO 浓度，mg/m³ |
| `stations[].temperature_2m` | number | 城市代表点气温，°C |
| `stations[].relative_humidity_2m` | number | 相对湿度，% |
| `stations[].surface_pressure` | number | 地面气压，hPa |
| `stations[].wind_speed_10m` | number | 风速，m/s |
| `stations[].wind_direction_10m` | number | 风向，度 |
| `stations[].precipitation` | number | 降水量，mm |
| `stations[].latitude` | null/number | 纬度，度 |
| `stations[].longitude` | null/number | 经度，度 |

### 错误与状态

- `422`：城市无效。
- `422`：请选择 2022—2025 年内的北京时间整点。
- `503`：站点数据与 CUDA 模型正在准备。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/stations/snapshot`，状态 `200`。

```json
{
  "time": "2025-12-30 12:00:00",
  "stations": [
    {
      "station_id": "1001A",
      "name": "万寿西宫",
      "city_id": "beijing",
      "ts": "2025-12-30 12:00:00"
    }
  ]
}
```

## GET /api/stations/history

station_id 必须存在于 stations 表；end 为2022—2025年的北京时间整点；hours 为24—168的整数。窗口包含 end。

读取或写入：data/app/stations.sqlite 的 stations / hourly。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `station_id` | string | `1001A` |
| `end` | string | `2025-12-30T12:00` |
| `hours` | integer | `72` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `station` | object | 单个站点元数据，或系统证据中的站点代摘要 |
| `station.station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `station.name` | string | 城市、站点、变量或来源的显示名称 |
| `station.city_id` | string | 城市 ID |
| `station.city_name` | string | 城市中文名 |
| `station.latitude` | number | 纬度，度 |
| `station.longitude` | number | 经度，度 |
| `hours` | integer | 小时网格长度或所选窗口长度，小时 |
| `points` | array | 按时间或提前时长排列的数据点列表 |
| `points[]` | object | 按时间或提前时长排列的数据点列表 |
| `points[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `points[].ts` | string | 小时记录的北京时间 |
| `points[].pm25` | null/number | 小时 PM2.5 浓度，μg/m³ |
| `points[].pm10` | null/number | 小时 PM10 浓度，μg/m³ |
| `points[].so2` | null/number | 小时 SO2 浓度，μg/m³ |
| `points[].no2` | null/number | 小时 NO2 浓度，μg/m³ |
| `points[].o3` | null/number | 小时 O3 浓度，μg/m³ |
| `points[].co` | null/number | 小时 CO 浓度，mg/m³ |
| `points[].temperature_2m` | number | 城市代表点气温，°C |
| `points[].relative_humidity_2m` | number | 相对湿度，% |
| `points[].surface_pressure` | number | 地面气压，hPa |
| `points[].wind_speed_10m` | number | 风速，m/s |
| `points[].wind_direction_10m` | number | 风向，度 |
| `points[].precipitation` | number | 降水量，mm |
| `points[].latitude` | number | 纬度，度 |
| `points[].longitude` | number | 经度，度 |

### 错误与状态

- `422`：历史窗口应为 24—168 小时。
- `422`：站点编号无效。
- `422`：请选择 2022—2025 年内的北京时间整点。
- `503`：站点数据与 CUDA 模型正在准备。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/stations/history`，状态 `200`。

```json
{
  "station": {
    "station_id": "1001A",
    "name": "万寿西宫",
    "city_id": "beijing",
    "city_name": "北京"
  },
  "hours": 72,
  "points": [
    {
      "station_id": "1001A",
      "ts": "2025-12-27 13:00:00",
      "pm25": 43.0,
      "pm10": 63.0
    }
  ]
}
```

## GET /api/stations/trend

station_id 必须存在；year 为2022—2025的整数。

读取或写入：data/app/stations.sqlite 的 stations / daily。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `station_id` | string | `1001A` |
| `year` | integer | `2025` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `station` | object | 单个站点元数据，或系统证据中的站点代摘要 |
| `station.station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `station.name` | string | 城市、站点、变量或来源的显示名称 |
| `station.city_id` | string | 城市 ID |
| `station.city_name` | string | 城市中文名 |
| `station.latitude` | number | 纬度，度 |
| `station.longitude` | number | 经度，度 |
| `year` | integer | 公历年份 |
| `points` | array | 按时间或提前时长排列的数据点列表 |
| `points[]` | object | 按时间或提前时长排列的数据点列表 |
| `points[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `points[].date` | string | 自然日日期 |
| `points[].pm25` | number | 小时 PM2.5 浓度，μg/m³ |
| `points[].valid_hours` | integer | 当前聚合内 PM2.5 有效小时数 |

### 错误与状态

- `422`：年份应为 2022—2025。
- `422`：站点编号无效。
- `503`：站点数据与 CUDA 模型正在准备。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/stations/trend`，状态 `200`。

```json
{
  "station": {
    "station_id": "1001A",
    "name": "万寿西宫",
    "city_id": "beijing",
    "city_name": "北京"
  },
  "year": 2025,
  "points": [
    {
      "station_id": "1001A",
      "date": "2025-01-01",
      "pm25": 19.125,
      "valid_hours": 24
    }
  ]
}
```

## GET /api/stations/models

无参数。runs 的键为 特征组:模型:h时长，GPU遥测数组已省略。

读取或写入：models/station_registry.json（省略 gpu.telemetry）。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `engine` | string | 实际推理框架及版本 |
| `splits` | object | 按时间划分的训练、选择、校准和测试边界 |
| `splits.train_end` | integer | 训练期最后年份 |
| `splits.validation` | integer | 验证期或验证指标 |
| `splits.test` | integer | 测试期或测试指标 |
| `runs` | object | 各实验的模型参数和评估，动态键见本节约定 |
| `runs.*` | object | 动态实验键对应的模型记录，结构与同级其他实验一致 |
| `runs.*.model` | string | 模型标识或所选模型 |
| `runs.*.variant` | string | 特征或模型消融组标识 |
| `runs.*.horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.*.metrics` | array | 训练/验证/测试的误差指标 |
| `runs.*.metrics[]` | object | 训练/验证/测试的误差指标 |
| `runs.*.metrics[].split` | string | 样本所属划分，如 validation/test |
| `runs.*.metrics[].scope` | string | 评估范围：all或beijing |
| `runs.*.metrics[].n` | integer | 参与当前统计的有效样本数 |
| `runs.*.metrics[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.*.metrics[].rmse` | number | 均方根误差，μg/m³ |
| `runs.*.metrics[].r2` | number | 决定系数，无量纲 |
| `runs.*.train_rows` | integer | 训练有效样本行数 |
| `runs.*.feature_count` | integer | 输入特征数量 |
| `runs.*.features` | array | 输入特征名列表或特征统计对象 |
| `runs.*.features[]` | string | 输入特征名列表或特征统计对象 |
| `runs.*.model_path` | string | 已保存模型的位置 |
| `runs.*.fit_and_eval_seconds` | number | 拟合与评估总耗时，秒 |
| `runs.*.feature_importance` | array | 树模型的特征重要性列表 |
| `runs.*.feature_importance[]` | object | 树模型的特征重要性列表 |
| `runs.*.feature_importance[].feature` | string | 特征名 |
| `runs.*.feature_importance[].importance` | number | 特征重要性，无量纲 |
| `runs.*.history_hours` | integer | 本轮历史输入窗口长度，小时 |
| `completed` | boolean | 已完成任务数或整体完成布尔值，按类型区分 |
| `selection_rule` | string | 推荐模型的选择规则说明 |
| `cohort` | string | 用于公平比较的样本队列约定 |
| `weather` | string | 天气来源或天气摘要 |
| `spark_completed` | boolean | 站点 Spark 训练是否完成 |
| `gpu` | object | 显卡型号或 GPU 执行证据对象，按类型区分 |
| `gpu.device` | string | 报告记录的执行设备名称 |
| `gpu.pytorch` | string | 报告记录的 PyTorch 版本 |
| `gpu.cuda_runtime` | string | PyTorch 使用的 CUDA 运行时版本 |
| `gpu.cudnn` | integer | cuDNN 版本编码 |
| `gpu.peak_torch_memory_mib` | number | PyTorch 峰值已分配显存，MiB |
| `gpu.peak_gpu_util_percent` | number | 采样到的最高 GPU 利用率，% |
| `gpu.train_origins` | integer | 训练起点样本数 |
| `gpu.best_epoch` | integer | 按模型选择期指标选出的轮次 |
| `gpu.epochs` | array | 实际训练各轮记录 |
| `gpu.epochs[]` | object | 实际训练各轮记录 |
| `gpu.epochs[].epoch` | integer | 训练轮次序号 |
| `gpu.epochs[].train_normalized_mse` | number | 训练归一化残差的均方误差 |
| `gpu.epochs[].validation_beijing_h6_rmse` | number | 北京验证集六小时 RMSE，μg/m³ |
| `gpu.epochs[].seconds` | number | 本轮或整个实验耗时，秒 |
| `gpu.epochs[].learning_rate` | number | 当前优化器学习率 |
| `gpu.elapsed_seconds` | number | 运行总耗时，秒 |
| `gpu.seed` | integer | 固定随机种子 |
| `recommended_by_horizon` | object | 按验证误差选择的推荐模型，键为提前小时字符串 |
| `recommended_by_horizon.*` | string | 提前小时字符串对应的推荐模型标识 |

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/stations/models`，状态 `200`。

```json
{
  "engine": "Spark ML + PyTorch CUDA",
  "splits": {
    "train_end": 2023,
    "validation": 2024,
    "test": 2025
  },
  "runs": {
    "persistence:h1": {
      "model": "persistence",
      "variant": "baseline",
      "horizon": 1,
      "metrics": [
        {
          "split": "validation",
          "scope": "all",
          "n": 624737,
          "mae": 5.129748998378518
        }
      ]
    },
    "persistence:h2": {
      "model": "persistence",
      "variant": "baseline",
      "horizon": 2,
      "metrics": [
        {
          "split": "validation",
          "scope": "all",
          "n": 623128,
          "mae": 7.918337805394718
        }
      ]
    },
    "persistence:h3": {
      "model": "persistence",
      "variant": "baseline",
      "horizon": 3,
      "metrics": [
        {
          "split": "validation",
          "scope": "all",
          "n": 622528,
          "mae": 10.159644224838079
        }
      ]
    },
    "persistence:h4": {
      "model": "persistence",
      "variant": "baseline",
      "horizon": 4,
      "metrics": [
        {
          "split": "validation",
          "scope": "all",
          "n": 622016,
          "mae": 12.068655790204753
        }
      ]
    }
  },
  "completed": true,
  "selection_rule": "Minimum Beijing station-hour validation RMSE per horizon; 2025 test is reporting only",
  "cohort": "Observed origin PM2.5; origin+6h within split; individual target must be observed; first72h excluded",
  "weather": "City-representative ERA5; 72h historical input; no future realized weather"
}
```

## GET /api/stations/forecast

station_id 必须存在；time 为2024-01-01T00:00至2025-12-31T17:00的北京时间整点；每年12月31日起点最晚17:00；model 为 best、rf、tcn72、persistence。

读取或写入：data/app/stations.sqlite 的 metadata / hourly / forecasts、models/station_registry.json。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `station_id` | string | `1001A` |
| `time` | string | `2025-12-30T12:00` |
| `model` | string | `best` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `station` | object | 单个站点元数据，或系统证据中的站点代摘要 |
| `station.station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `station.name` | string | 城市、站点、变量或来源的显示名称 |
| `station.city_id` | string | 城市 ID |
| `station.city_name` | string | 城市中文名 |
| `station.latitude` | number | 纬度，度 |
| `station.longitude` | number | 经度，度 |
| `origin` | string | 最后可用实测的预测起点，北京时间 |
| `current` | number | 预测起点的 PM2.5，μg/m³ |
| `model` | string | 模型标识或所选模型 |
| `points` | array | 按时间或提前时长排列的数据点列表 |
| `points[]` | object | 按时间或提前时长排列的数据点列表 |
| `points[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `points[].origin` | string | 最后可用实测的预测起点，北京时间 |
| `points[].target` | string | 预测目标时刻，北京时间 |
| `points[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `points[].model` | string | 模型标识或所选模型 |
| `points[].prediction` | number | 模型预测 PM2.5；v3 为中位数，μg/m³ |
| `points[].actual` | null/number | 目标时刻实测 PM2.5，未到达为 null，μg/m³ |
| `points[].baseline` | number | 起点 PM2.5 不变的持续性预测，μg/m³ |
| `points[].rf` | number | 同一样本的随机森林预测，μg/m³ |
| `points[].tcn72` | number | 同一样本的旧版 TCN 预测，μg/m³ |
| `split` | string | 样本所属划分，如 validation/test |
| `history` | array | 过去污染与天气小时序列 |
| `history[]` | object | 过去污染与天气小时序列 |
| `history[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `history[].ts` | string | 小时记录的北京时间 |
| `history[].pm25` | null/number | 小时 PM2.5 浓度，μg/m³ |
| `history[].pm10` | null/number | 小时 PM10 浓度，μg/m³ |
| `history[].so2` | null/number | 小时 SO2 浓度，μg/m³ |
| `history[].no2` | null/number | 小时 NO2 浓度，μg/m³ |
| `history[].o3` | null/number | 小时 O3 浓度，μg/m³ |
| `history[].co` | null/number | 小时 CO 浓度，mg/m³ |
| `history[].temperature_2m` | number | 城市代表点气温，°C |
| `history[].relative_humidity_2m` | number | 相对湿度，% |
| `history[].surface_pressure` | number | 地面气压，hPa |
| `history[].wind_speed_10m` | number | 风速，m/s |
| `history[].wind_direction_10m` | number | 风向，度 |
| `history[].precipitation` | number | 降水量，mm |
| `history[].latitude` | number | 纬度，度 |
| `history[].longitude` | number | 经度，度 |

### 错误与状态

- `404`：此时点没有完整六小时预测。
- `404`：此时点的模型输出缺失。
- `404`：该站点在此起点没有 PM₂.₅ 实测，请选择其他时刻。
- `422`：历史窗口应为 24—168 小时。
- `422`：站点编号无效。
- `422`：该六小时窗口跨越评估年度边界，请选择当日 17:00 或更早。
- `422`：请选择 2022—2025 年内的北京时间整点。
- `422`：预测回放支持 2024—2025 年，最晚起点为 2025-12-31 17:00。
- `422`：预测模型无效。
- `503`：模型版本更新中。
- `503`：站点数据与 CUDA 模型正在准备。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/stations/forecast`，状态 `200`。

```json
{
  "station": {
    "station_id": "1001A",
    "name": "万寿西宫",
    "city_id": "beijing",
    "city_name": "北京"
  },
  "origin": "2025-12-30 12:00:00",
  "current": 3.0,
  "model": "best",
  "points": [
    {
      "station_id": "1001A",
      "origin": "2025-12-30 12:00:00",
      "target": "2025-12-30 13:00:00",
      "horizon": 1
    }
  ],
  "split": "test",
  "history": [
    {
      "station_id": "1001A",
      "ts": "2025-12-27 13:00:00",
      "pm25": 43.0,
      "pm10": 63.0
    }
  ]
}
```

## GET /api/live/meta

无参数。始终可查询状态；ready仅表示有快照，是否能展示当前预测要同时检查 usable。

读取或写入：data/live/latest.json、reports/live_progress.json、data/live/online.sqlite。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `ready` | boolean | 相应模块已有可读取的产物；实时预测还应检查 usable |
| `current_time` | string | 服务端当前北京时间 |
| `refresh` | object | 后台轮次状态对象 |
| `refresh.phase` | string | 当前流水线阶段标识 |
| `refresh.updated_at` | string | 进度更新时间，北京时间 |
| `refresh.cycle_id` | string | 数据采集与预测轮次标识 |
| `refresh.completed_at` | string | 训练或本轮处理完成时间 |
| `refreshing` | boolean | 后台是否正在运行一个轮次 |
| `next_refresh` | string | 下一次计划刷新时间；尚未计算为 null |
| `refresh_interval_seconds` | integer | 常规自动刷新间隔，秒 |
| `cycle_id` | string | 数据采集与预测轮次标识 |
| `issued_at` | string | 预测实际发布时间，北京时间 |
| `origin` | string | 最后可用实测的预测起点，北京时间 |
| `timezone` | string | 时间所属时区 |
| `current` | number | 预测起点的 PM2.5，μg/m³ |
| `inference_device` | string | 本次推理实际执行设备 |
| `model_name` | string | 模型显示名 |
| `engine` | string | 实际推理框架及版本 |
| `forecast_stations` | integer | 本轮满足输入要求、可预测的北京站点数 |
| `beijing_stations` | integer | 模型目录中的北京站点总数 |
| `history_hours` | integer | 本轮历史输入窗口长度，小时 |
| `extension_hours` | integer | 旧模型尾部递推小时数；新直接模型为0 |
| `spark_version` | string | 报告记录的 Spark 版本 |
| `feature_count` | integer | 输入特征数量 |
| `air_sources` | array | 空气质量数据来源及用途 |
| `air_sources[]` | object | 空气质量数据来源及用途 |
| `air_sources[].name` | string | 城市、站点、变量或来源的显示名称 |
| `air_sources[].url` | string | 来源地址 |
| `air_sources[].role` | string | 来源在本项目中的作用 |
| `weather_source` | object | 天气资料来源及类型 |
| `weather_source.name` | string | 城市、站点、变量或来源的显示名称 |
| `weather_source.url` | string | 来源地址 |
| `weather_source.type` | string | 资料类型说明 |
| `source_fetched_at` | string | 本轮来源采集结束时间 |
| `method_note` | string | 预测方法与城市均值口径说明 |
| `accuracy_note` | string | 实时精度的适用边界说明 |
| `source_errors` | array | 本轮可选来源的失败列表 |
| `source_errors[]` | object | 本轮可选来源的失败列表 |
| `source_errors[].kind` | string | 失败或采集来源的类别 |
| `source_errors[].error` | string | 失败原因，成功时为 null |
| `nominal_coverage` | number | 区间名义覆盖概率，0—1；不等于实际覆盖率 |
| `interval_note` | string | 区间校准方法与适用边界 |
| `future_weather` | boolean | 是否使用未来天气输入 |
| `usable` | boolean | 当前快照是否仍可用作未来预测 |
| `data_age_minutes` | number | 当前时间距实测起点的分钟数 |
| `expired` | boolean | 当前预测是否已过期 |
| `stations` | array | 站点目录或站点数量，按类型区分 |
| `stations[]` | object | 站点目录或站点数量，按类型区分 |
| `stations[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `stations[].name` | string | 城市、站点、变量或来源的显示名称 |
| `stations[].latitude` | number | 纬度，度 |
| `stations[].longitude` | number | 经度，度 |
| `stations[].current` | null/number | 预测起点的 PM2.5，μg/m³ |
| `stations[].available` | boolean | 该站点是否满足本轮推理输入要求 |
| `stations[].reason` | null/string | 站点不可预测的原因；可预测时为 null |
| `stations[].valid_history_hours` | integer | 历史窗口内 PM2.5 有效小时数 |
| `online_evaluation` | object | 当前模型版本的简要在线误差 |
| `online_evaluation.matched` | integer | 已有真实标签的在线样本数 |
| `online_evaluation.pending` | integer | 已发布且等待实测到达的样本数 |
| `online_evaluation.by_horizon` | array | 按提前小时分组的指标列表 |
| `online_evaluation.by_horizon[]` | object | 按提前小时分组的指标列表 |
| `online_evaluation.by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `online_evaluation.by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `online_evaluation.by_horizon[].pending` | integer | 已发布且等待实测到达的样本数 |
| `online_evaluation.by_horizon[].mae` | null/number | 平均绝对误差，μg/m³ |
| `online_evaluation.by_horizon[].rmse` | null/number | 均方根误差，μg/m³ |
| `online_evaluation.by_horizon[].baseline_rmse` | null/number | 同样本持续性基线的 RMSE，μg/m³ |
| `online_evaluation.note` | string | 统计、来源或使用边界的文字说明 |

尚无快照时，只返回公共状态、usable=false、stations=[]；旧版快照中的新增字段可能为null。

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/live/meta`，状态 `200`。

```json
{
  "ready": true,
  "current_time": "2026-10-23T00:11:43.649757+08:00",
  "refresh": {
    "phase": "complete",
    "updated_at": "2026-10-23T00:08:50.423528+08:00",
    "cycle_id": "20261023T000641_451f295f",
    "completed_at": "2026-10-23T00:08:50.423496+08:00"
  },
  "refreshing": false,
  "next_refresh": "2026-10-23T00:18:50.441602+08:00",
  "refresh_interval_seconds": 600,
  "cycle_id": "20261023T000641_451f295f"
}
```

## GET /api/live/forecast

station_id 为 mean 或已接入的北京站点编号。仅返回仍有效的当前预测：实测年龄≤180分钟，且全部六个目标时刻仍在未来。城市均值来自本轮可预测站点等权平均。单站响应包含站点元数据，均值响应包含 nominal_coverage / interval_note。

读取或写入：data/live/latest.json。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `station_id` | string | `mean` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `name` | string | 城市、站点、变量或来源的显示名称 |
| `issued_at` | string | 预测实际发布时间，北京时间 |
| `origin` | string | 最后可用实测的预测起点，北京时间 |
| `current` | number | 预测起点的 PM2.5，μg/m³ |
| `points` | array | 按时间或提前时长排列的数据点列表 |
| `points[]` | object | 按时间或提前时长排列的数据点列表 |
| `points[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `points[].target` | string | 预测目标时刻，北京时间 |
| `points[].lead_from_observation` | integer | 目标距最后实测起点的小时数，可能大于 horizon |
| `points[].method` | string | direct 为直接输出，recursive_extension 为旧版尾部递推 |
| `points[].prediction` | number | 模型预测 PM2.5；v3 为中位数，μg/m³ |
| `points[].lower` | number | 发布时保存的预测区间下限，μg/m³ |
| `points[].upper` | number | 发布时保存的预测区间上限，μg/m³ |
| `points[].baseline` | number | 起点 PM2.5 不变的持续性预测，μg/m³ |
| `points[].actual` | null | 目标时刻实测 PM2.5，未到达为 null，μg/m³ |
| `history` | array | 过去污染与天气小时序列 |
| `history[]` | object | 过去污染与天气小时序列 |
| `history[].ts` | string | 小时记录的北京时间 |
| `history[].pm25` | null/number | 小时 PM2.5 浓度，μg/m³ |
| `history[].observed_stations` | integer | 该历史小时参与聚合的有效站点数 |
| `history[].temperature_2m` | number | 城市代表点气温，°C |
| `history[].relative_humidity_2m` | number | 相对湿度，% |
| `history[].surface_pressure` | number | 地面气压，hPa |
| `history[].wind_speed_10m` | number | 风速，m/s |
| `history[].wind_direction_10m` | number | 风向，度 |
| `history[].precipitation` | number | 降水量，mm |
| `weather_next` | array | 未来目标时刻的城市天气预报列表 |
| `weather_next[]` | object | 未来目标时刻的城市天气预报列表 |
| `weather_next[].ts` | string | 小时记录的北京时间 |
| `weather_next[].forecast_reference_time` | string | 当前固定提前量天气预报的参考发布时间 |
| `weather_next[].temperature_2m` | number | 城市代表点气温，°C |
| `weather_next[].relative_humidity_2m` | number | 相对湿度，% |
| `weather_next[].surface_pressure` | number | 地面气压，hPa |
| `weather_next[].wind_speed_10m` | number | 风速，m/s |
| `weather_next[].wind_direction_10m` | number | 风向，度 |
| `weather_next[].precipitation` | number | 降水量，mm |
| `nominal_coverage` | number | 区间名义覆盖概率，0—1；不等于实际覆盖率 |
| `interval_note` | string | 区间校准方法与适用边界 |
| `city_id` | string | 城市 ID |
| `city_name` | string | 城市中文名 |
| `latitude` | number | 纬度，度 |
| `longitude` | number | 经度，度 |
| `available` | boolean | 该站点是否满足本轮推理输入要求 |
| `valid_history_hours` | integer | 历史窗口内 PM2.5 有效小时数 |
| `reason` | null | 站点不可预测的原因；可预测时为 null |

### 错误与状态

- `409`：所选站点的 reason（缺少实测或历史输入不足）。
- `409`：预测结果已过期，正在等待新一轮实时更新。
- `422`：请选择已接入的北京站点。
- `503`：正在获取实时空气质量和气象资料，请稍后查看。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/live/forecast`，状态 `200`。

```json
{
  "station_id": "mean",
  "name": "北京覆盖站点均值",
  "issued_at": "2026-10-23T00:08:48.045975+08:00",
  "origin": "2026-10-22T23:00:00+08:00",
  "current": 40.421051025390625,
  "points": [
    {
      "horizon": 1,
      "target": "2026-10-23T01:00:00+08:00",
      "lead_from_observation": 2,
      "method": "direct"
    }
  ],
  "history": [
    {
      "ts": "2026-10-20T00:00:00+08:00",
      "pm25": 37.31578826904297,
      "observed_stations": 19,
      "temperature_2m": 15.0
    }
  ]
}
```

单站实际响应节选：`GET /api/live/forecast?station_id=1001A`。

```json
{
  "station_id": "1001A",
  "city_id": "beijing",
  "city_name": "北京",
  "name": "万寿西宫",
  "latitude": 39.8786,
  "longitude": 116.3611,
  "available": true
}
```

## POST /api/live/refresh

无请求体。一次仅允许一个更新过程；两次启动至少间隔120秒。无论 accepted 为 true 或 false，HTTP 状态均为202。前端应显示 message 并轮询 /api/live/meta.refresh。

读取或写入：后台工作线程状态；异步轮次写 reports/live_progress.json，完成后发布 data/live/latest.json。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `accepted` | boolean | 刷新请求是否被接受 |
| `message` | string | 供用户显示的中文状态提示 |

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。
- `accepted=false`：数据更新正在进行。
- `accepted=false`：请稍后刷新，两次更新至少间隔两分钟。

### 实际响应节选

请求：`POST /api/live/refresh`，状态 `202`。

```json
{
  "accepted": true,
  "message": "已开始更新实时数据与六小时预测"
}
```

## GET /api/live/export

station_id 与 /api/live/forecast 相同，时效检查完全相同。

读取或写入：data/live/latest.json。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `station_id` | string | `mean` |

### 返回字段

CSV列顺序：站点、发布时间、最新实测起点、目标时刻、未来小时、距实测小时、预测PM2.5、持续基线、区间下限、区间上限、预测方式。浓度均为μg/m³，小时列为整数；下限和上限可能为空。
编码 UTF-8 BOM；Content-Type 为 text/csv；Content-Disposition 为 attachment。

### 错误与状态

- `409`：所选站点的 reason（缺少实测或历史输入不足）。
- `409`：预测结果已过期，正在等待新一轮实时更新。
- `422`：请选择已接入的北京站点。
- `503`：正在获取实时空气质量和气象资料，请稍后查看。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/live/export`，状态 `200`。

```csv
站点,发布时间,最新实测起点,目标时刻,未来小时,距实测小时,预测PM2.5,持续基线,区间下限,区间上限,预测方式
mean,2026-10-23T00:08:48.045975+08:00,2026-10-22T23:00:00+08:00,2026-10-23T01:00:00+08:00,1,2,38.15666580200195,40.421051025390625,29.326900482177734,47.28044891357422,direct
mean,2026-10-23T00:08:48.045975+08:00,2026-10-22T23:00:00+08:00,2026-10-23T02:00:00+08:00,2,3,37.7441520690918,40.421051025390625,27.527074813842773,48.6026725769043,direct
```

## GET /api/live/evaluation

start/end 为 ISO 日期，默认 end=当前北京时间日期、start=end减13天；校验0≤(end-start).days≤90。station_id 可省略，指定时须为北京站点；horizon 可省略或1—6；checkpoint 可省略或64位小写十六进制哈希。省略版本时优先采用最新发布快照的版本。日期过滤作用于 target，不是 issued_at。

读取或写入：data/live/online.sqlite、data/live/latest.json、data/stations/station_catalog.json。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `start` | string/null | `省略；动态默认规则见上文` |
| `end` | string/null | `省略；动态默认规则见上文` |
| `station_id` | string/null | `省略；动态默认规则见上文` |
| `horizon` | integer/null | `省略；动态默认规则见上文` |
| `checkpoint` | string/null | `省略；动态默认规则见上文` |

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `checkpoint_sha256` | string | 模型权重原始字节的 SHA-256 |
| `models` | array | 可选模型版本或模型登记对象 |
| `models[]` | object | 可选模型版本或模型登记对象 |
| `models[].checkpoint_sha256` | string | 模型权重原始字节的 SHA-256 |
| `models[].model_name` | null/string | 模型显示名 |
| `models[].first_issue` | string | 所选队列最早发布时间 |
| `models[].last_issue` | string | 所选队列最晚发布时间 |
| `models[].stored` | integer | 该版本数据库原始发布记录数，尚未去重 |
| `filters` | object | 本次实际应用的过滤条件 |
| `filters.start` | string | 起始日期或时间（上下文决定） |
| `filters.end` | string | 结束日期或时间（上下文决定） |
| `filters.station_id` | null | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `filters.horizon` | null | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `summary` | object | 数据规模或误差的摘要对象 |
| `summary.n` | integer | 参与当前统计的有效样本数 |
| `summary.pending` | integer | 已发布且等待实测到达的样本数 |
| `summary.mae` | number | 平均绝对误差，μg/m³ |
| `summary.rmse` | number | 均方根误差，μg/m³ |
| `summary.bias` | number | 平均有符号误差，预测减实测，μg/m³ |
| `summary.baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `summary.rmse_skill` | number | 1减模型RMSE/基线RMSE，无量纲 |
| `summary.interval_n` | integer | 有实测且发布时保存了上下限的样本数 |
| `summary.coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `summary.mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `by_horizon` | array | 按提前小时分组的指标列表 |
| `by_horizon[]` | object | 按提前小时分组的指标列表 |
| `by_horizon[].key` | integer | 分组键，随 by_day/by_station/by_horizon/by_regime 而定 |
| `by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `by_horizon[].pending` | integer | 已发布且等待实测到达的样本数 |
| `by_horizon[].mae` | null/number | 平均绝对误差，μg/m³ |
| `by_horizon[].rmse` | null/number | 均方根误差，μg/m³ |
| `by_horizon[].bias` | null/number | 平均有符号误差，预测减实测，μg/m³ |
| `by_horizon[].baseline_rmse` | null/number | 同样本持续性基线的 RMSE，μg/m³ |
| `by_horizon[].rmse_skill` | number | 1减模型RMSE/基线RMSE，无量纲 |
| `by_horizon[].interval_n` | integer | 有实测且发布时保存了上下限的样本数 |
| `by_horizon[].coverage` | null/number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `by_horizon[].mean_width` | null/number | 区间上限减下限的平均值，μg/m³ |
| `by_day` | array | 按目标自然日分组的指标列表 |
| `by_day[]` | object | 按目标自然日分组的指标列表 |
| `by_day[].key` | string | 分组键，随 by_day/by_station/by_horizon/by_regime 而定 |
| `by_day[].n` | integer | 参与当前统计的有效样本数 |
| `by_day[].pending` | integer | 已发布且等待实测到达的样本数 |
| `by_day[].mae` | null/number | 平均绝对误差，μg/m³ |
| `by_day[].rmse` | null/number | 均方根误差，μg/m³ |
| `by_day[].bias` | null/number | 平均有符号误差，预测减实测，μg/m³ |
| `by_day[].baseline_rmse` | null/number | 同样本持续性基线的 RMSE，μg/m³ |
| `by_day[].rmse_skill` | number | 1减模型RMSE/基线RMSE，无量纲 |
| `by_day[].interval_n` | integer | 有实测且发布时保存了上下限的样本数 |
| `by_day[].coverage` | null/number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `by_day[].mean_width` | null/number | 区间上限减下限的平均值，μg/m³ |
| `by_station` | array | 按站点分组的指标列表 |
| `by_station[]` | object | 按站点分组的指标列表 |
| `by_station[].key` | string | 分组键，随 by_day/by_station/by_horizon/by_regime 而定 |
| `by_station[].n` | integer | 参与当前统计的有效样本数 |
| `by_station[].pending` | integer | 已发布且等待实测到达的样本数 |
| `by_station[].mae` | number | 平均绝对误差，μg/m³ |
| `by_station[].rmse` | number | 均方根误差，μg/m³ |
| `by_station[].bias` | number | 平均有符号误差，预测减实测，μg/m³ |
| `by_station[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `by_station[].rmse_skill` | null/number | 1减模型RMSE/基线RMSE，无量纲 |
| `by_station[].interval_n` | integer | 有实测且发布时保存了上下限的样本数 |
| `by_station[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `by_station[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `by_regime` | array | 按浓度和突变分组的指标列表 |
| `by_regime[]` | object | 按浓度和突变分组的指标列表 |
| `by_regime[].key` | string | 分组键，随 by_day/by_station/by_horizon/by_regime 而定 |
| `by_regime[].n` | integer | 参与当前统计的有效样本数 |
| `by_regime[].pending` | integer | 已发布且等待实测到达的样本数 |
| `by_regime[].mae` | null/number | 平均绝对误差，μg/m³ |
| `by_regime[].rmse` | null/number | 均方根误差，μg/m³ |
| `by_regime[].bias` | null/number | 平均有符号误差，预测减实测，μg/m³ |
| `by_regime[].baseline_rmse` | null/number | 同样本持续性基线的 RMSE，μg/m³ |
| `by_regime[].rmse_skill` | number | 1减模型RMSE/基线RMSE，无量纲 |
| `by_regime[].interval_n` | integer | 有实测且发布时保存了上下限的样本数 |
| `by_regime[].coverage` | null/number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `by_regime[].mean_width` | null/number | 区间上限减下限的平均值，μg/m³ |
| `failures` | array | 按绝对误差排序的最差在线样本，最多20条 |
| `failures[]` | object | 按绝对误差排序的最差在线样本，最多20条 |
| `failures[].cycle_id` | string | 数据采集与预测轮次标识 |
| `failures[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `failures[].issued_at` | string | 预测实际发布时间，北京时间 |
| `failures[].origin` | string | 最后可用实测的预测起点，北京时间 |
| `failures[].target` | string | 预测目标时刻，北京时间 |
| `failures[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `failures[].lead_from_observation` | integer | 目标距最后实测起点的小时数，可能大于 horizon |
| `failures[].prediction` | number | 模型预测 PM2.5；v3 为中位数，μg/m³ |
| `failures[].baseline` | number | 起点 PM2.5 不变的持续性预测，μg/m³ |
| `failures[].method` | string | direct 为直接输出，recursive_extension 为旧版尾部递推 |
| `failures[].checkpoint_sha256` | string | 模型权重原始字节的 SHA-256 |
| `failures[].actual` | number | 目标时刻实测 PM2.5，未到达为 null，μg/m³ |
| `failures[].actual_received_at` | string | 真实标签被收到并写入的时间，未到达为 null |
| `failures[].actual_cycle_id` | string | 提供该真实标签的采集轮次，未到达为 null |
| `failures[].lower` | number | 发布时保存的预测区间下限，μg/m³ |
| `failures[].upper` | number | 发布时保存的预测区间上限，μg/m³ |
| `failures[].nominal_coverage` | number | 区间名义覆盖概率，0—1；不等于实际覆盖率 |
| `failures[].model_name` | string | 模型显示名 |
| `failures[].rn` | integer | 去重排序内部序号；保留行均为1 |
| `failures[].absolute_error` | number | 单个样本绝对误差，μg/m³ |
| `collection` | object | 真实在线积累时间与起点小时覆盖情况 |
| `collection.first_issue` | string | 所选队列最早发布时间 |
| `collection.last_issue` | string | 所选队列最晚发布时间 |
| `collection.elapsed_days` | number | 最早至最晚发布的实际跨度，天 |
| `collection.observed_origin_hours` | integer | 队列中不同实测起点小时数 |
| `collection.origin_hour_coverage` | number | 不同起点小时数/起点范围内预期小时数，0—1 |
| `collection.recommended_days` | integer | 判断稳定实时精度建议积累的最少天数 |
| `collection.mature` | boolean | 同时满足积累跨度至少7天、起点小时覆盖率至少80%的布尔值 |
| `note` | string | 统计、来源或使用边界的文字说明 |
| `by_horizon[].horizon` | integer/null | 提前小时；实时接口表示距发布时间所在整点的未来小时 |

### 错误与状态

- `422`：请选择不超过 90 天且起止顺序正确的日期范围。
- `422`：请选择北京站点。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/live/evaluation`，状态 `200`。

```json
{
  "checkpoint_sha256": "90a9fbbd5415a6a1a68e357d97c5eb83c8b6e5b74c8db6077b868249d502a81c",
  "models": [
    {
      "checkpoint_sha256": "90a9fbbd5415a6a1a68e357d97c5eb83c8b6e5b74c8db6077b868249d502a81c",
      "model_name": "72h历史 + 未来天气 · 9时长分位数TCN",
      "first_issue": "2026-10-22T22:54:22.067822+08:00",
      "last_issue": "2026-10-23T00:08:48.045975+08:00"
    }
  ],
  "filters": {
    "start": "2026-10-10",
    "end": "2026-10-23",
    "station_id": null,
    "horizon": null
  },
  "summary": {
    "n": 19,
    "pending": 323,
    "mae": 2.249502081620066,
    "rmse": 4.786169293232774
  },
  "by_horizon": [
    {
      "key": 1,
      "n": 19,
      "pending": 38,
      "mae": 2.249502081620066
    }
  ],
  "by_day": [
    {
      "key": "2026-10-22",
      "n": 19,
      "pending": 0,
      "mae": 2.249502081620066
    }
  ],
  "by_station": [
    {
      "key": "1001A",
      "n": 1,
      "pending": 17,
      "mae": 1.63775634765625
    }
  ]
}
```

## GET /api/live/evaluation/export

参数、默认值、去重口径与 /api/live/evaluation 一致。导出保留未到达实测的空单元格。

读取或写入：同 /api/live/evaluation。

### 参数

| 名称 | 类型 | 默认值 |
| --- | --- | --- |
| `start` | string/null | `省略；动态默认规则见上文` |
| `end` | string/null | `省略；动态默认规则见上文` |
| `station_id` | string/null | `省略；动态默认规则见上文` |
| `horizon` | integer/null | `省略；动态默认规则见上文` |
| `checkpoint` | string/null | `省略；动态默认规则见上文` |

### 返回字段

CSV列顺序：station_id、issued_at、origin、target、horizon、lead_from_observation、prediction、baseline、lower、upper、actual、actual_received_at、checkpoint_sha256、method。字段含义同在线核验接口；时间为北京时间，浓度为μg/m³。
编码 UTF-8 BOM；Content-Type 为 text/csv；Content-Disposition 为 attachment。

### 错误与状态

- `422`：请选择不超过 90 天且起止顺序正确的日期范围。
- `422`：请选择北京站点。
- `422`：参数类型、日期格式、取值范围或正则校验失败，格式见公共约定。

### 实际响应节选

请求：`GET /api/live/evaluation/export`，状态 `200`。

```csv
station_id,issued_at,origin,target,horizon,lead_from_observation,prediction,baseline,lower,upper,actual,actual_received_at,checkpoint_sha256,method
1001A,2026-10-22T22:54:22.067822+08:00,2026-10-22T22:00:00+08:00,2026-10-22T23:00:00+08:00,1,1,37.36224365234375,37.0,30.224626541137695,44.66853332519531,39.0,2026-10-22T23:34:01.966441+08:00,90a9fbbd5415a6a1a68e357d97c5eb83c8b6e5b74c8db6077b868249d502a81c,direct
1003A,2026-10-22T22:54:22.067822+08:00,2026-10-22T22:00:00+08:00,2026-10-22T23:00:00+08:00,1,1,34.56182861328125,34.0,27.21852684020996,42.072296142578125,34.0,2026-10-22T23:34:01.966441+08:00,90a9fbbd5415a6a1a68e357d97c5eb83c8b6e5b74c8db6077b868249d502a81c,direct
```

## GET /api/live/model

无参数。ready=false 时只返回 ready 和 message；ready=true 时报告字段与保存的离线训练报告一致。

读取或写入：reports/forecast_model_results.json（省略 gpu.telemetry）。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `ready` | boolean | 相应模块已有可读取的产物；实时预测还应检查 usable |
| `completed_at` | string | 训练或本轮处理完成时间 |
| `model` | string | 模型标识或所选模型 |
| `data` | object | 离线模型训练数据说明 |
| `data.start` | string | 起始日期或时间（上下文决定） |
| `data.hours` | integer | 小时网格长度或所选窗口长度，小时 |
| `data.stations_metadata` | array | 训练所用站点元数据列表 |
| `data.stations_metadata[]` | object | 训练所用站点元数据列表 |
| `data.stations_metadata[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `data.stations_metadata[].city_id` | string | 城市 ID |
| `data.stations_metadata[].city_name` | string | 城市中文名 |
| `data.stations_metadata[].name` | string | 城市、站点、变量或来源的显示名称 |
| `data.stations_metadata[].latitude` | number | 纬度，度 |
| `data.stations_metadata[].longitude` | number | 经度，度 |
| `data.cities` | array | 城市目录或城市 ID 列表，按实际结构读取 |
| `data.cities[]` | string | 城市目录或城市 ID 列表，按实际结构读取 |
| `data.sequence_columns` | array | 历史输入通道的有序字段列表 |
| `data.sequence_columns[]` | string | 历史输入通道的有序字段列表 |
| `data.weather_columns` | array | 未来天气通道的有序字段名 |
| `data.weather_columns[]` | string | 未来天气通道的有序字段名 |
| `data.weather_model` | string | 天气模型标识 |
| `data.weather_lead_hours` | integer | 天气预测相对其有效时刻的固定提前量，小时 |
| `data.weather_valid_hours` | integer | 可用城市×天气小时记录数 |
| `data.hdfs` | string | 相关数据在 HDFS 中的路径 |
| `data.spark_version` | string | 报告记录的 Spark 版本 |
| `data.source_manifest_sha256` | string | 原始来源清单的 SHA-256 |
| `data.splits` | object | 按时间划分的训练、选择、校准和测试边界 |
| `data.splits.train` | string | 训练期或训练样本数 |
| `data.splits.selection` | string | 模型选择期或选择指标 |
| `data.splits.calibration` | string | 独立区间校准期或样本数 |
| `data.splits.test` | string | 测试期或测试指标 |
| `samples` | object | 各时间段有效起点样本数；每个起点可有多个提前时长标签 |
| `samples.train` | integer | 训练期或训练样本数 |
| `samples.selection` | integer | 模型选择期或选择指标 |
| `samples.calibration` | integer | 独立区间校准期或样本数 |
| `samples.test` | integer | 测试期或测试指标 |
| `runs` | object | 各实验的模型参数和评估，动态键见本节约定 |
| `runs.history_only` | object | 使用相同数据与划分、关闭未来天气输入的对照实验 |
| `runs.history_only.selection` | object | 模型选择期或选择指标 |
| `runs.history_only.selection.by_horizon` | array | 按提前小时分组的指标列表 |
| `runs.history_only.selection.by_horizon[]` | object | 按提前小时分组的指标列表 |
| `runs.history_only.selection.by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.selection.by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.selection.by_horizon[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.selection.by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.selection.by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.selection.by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.selection.by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.selection.city_by_horizon` | array | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.history_only.selection.city_by_horizon[]` | object | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.history_only.selection.city_by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.selection.city_by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.selection.city_by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.selection.city_by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.selection.city_by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.selection.city_by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.selection.regimes` | object | 按实测浓度或变化幅度划分的离线测试指标 |
| `runs.history_only.selection.regimes.pm_lt35` | array | 目标PM2.5小于35 μg/m³的分组 |
| `runs.history_only.selection.regimes.pm_lt35[]` | object | 目标PM2.5小于35 μg/m³的分组 |
| `runs.history_only.selection.regimes.pm_lt35[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.selection.regimes.pm_lt35[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.selection.regimes.pm_lt35[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.selection.regimes.pm_lt35[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.selection.regimes.pm_lt35[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.selection.regimes.pm_lt35[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.selection.regimes.pm_lt35[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.selection.regimes.pm_35_75` | array | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.history_only.selection.regimes.pm_35_75[]` | object | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.history_only.selection.regimes.pm_35_75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.selection.regimes.pm_35_75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.selection.regimes.pm_35_75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.selection.regimes.pm_35_75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.selection.regimes.pm_35_75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.selection.regimes.pm_35_75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.selection.regimes.pm_35_75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.selection.regimes.pm_ge75` | array | 目标PM2.5至少75 μg/m³的分组 |
| `runs.history_only.selection.regimes.pm_ge75[]` | object | 目标PM2.5至少75 μg/m³的分组 |
| `runs.history_only.selection.regimes.pm_ge75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.selection.regimes.pm_ge75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.selection.regimes.pm_ge75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.selection.regimes.pm_ge75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.selection.regimes.pm_ge75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.selection.regimes.pm_ge75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.selection.regimes.pm_ge75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.selection.regimes.abrupt_ge20` | array | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.history_only.selection.regimes.abrupt_ge20[]` | object | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.history_only.selection.regimes.abrupt_ge20[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.selection.regimes.abrupt_ge20[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.selection.regimes.abrupt_ge20[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.selection.regimes.abrupt_ge20[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.selection.regimes.abrupt_ge20[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.selection.regimes.abrupt_ge20[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.selection.regimes.abrupt_ge20[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.test` | object | 测试期或测试指标 |
| `runs.history_only.test.by_horizon` | array | 按提前小时分组的指标列表 |
| `runs.history_only.test.by_horizon[]` | object | 按提前小时分组的指标列表 |
| `runs.history_only.test.by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.test.by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.test.by_horizon[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.test.by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.test.by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.test.by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.test.by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.test.city_by_horizon` | array | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.history_only.test.city_by_horizon[]` | object | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.history_only.test.city_by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.test.city_by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.test.city_by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.test.city_by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.test.city_by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.test.city_by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.test.regimes` | object | 按实测浓度或变化幅度划分的离线测试指标 |
| `runs.history_only.test.regimes.pm_lt35` | array | 目标PM2.5小于35 μg/m³的分组 |
| `runs.history_only.test.regimes.pm_lt35[]` | object | 目标PM2.5小于35 μg/m³的分组 |
| `runs.history_only.test.regimes.pm_lt35[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.test.regimes.pm_lt35[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.test.regimes.pm_lt35[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.test.regimes.pm_lt35[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.test.regimes.pm_lt35[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.test.regimes.pm_lt35[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.test.regimes.pm_lt35[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.test.regimes.pm_35_75` | array | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.history_only.test.regimes.pm_35_75[]` | object | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.history_only.test.regimes.pm_35_75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.test.regimes.pm_35_75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.test.regimes.pm_35_75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.test.regimes.pm_35_75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.test.regimes.pm_35_75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.test.regimes.pm_35_75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.test.regimes.pm_35_75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.test.regimes.pm_ge75` | array | 目标PM2.5至少75 μg/m³的分组 |
| `runs.history_only.test.regimes.pm_ge75[]` | object | 目标PM2.5至少75 μg/m³的分组 |
| `runs.history_only.test.regimes.pm_ge75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.test.regimes.pm_ge75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.test.regimes.pm_ge75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.test.regimes.pm_ge75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.test.regimes.pm_ge75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.test.regimes.pm_ge75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.test.regimes.pm_ge75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.test.regimes.abrupt_ge20` | array | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.history_only.test.regimes.abrupt_ge20[]` | object | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.history_only.test.regimes.abrupt_ge20[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.history_only.test.regimes.abrupt_ge20[].n` | integer | 参与当前统计的有效样本数 |
| `runs.history_only.test.regimes.abrupt_ge20[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.history_only.test.regimes.abrupt_ge20[].rmse` | number | 均方根误差，μg/m³ |
| `runs.history_only.test.regimes.abrupt_ge20[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.history_only.test.regimes.abrupt_ge20[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.history_only.test.regimes.abrupt_ge20[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.history_only.station_adjustment` | array | 各提前时长的站点区间独立校准扩大量，μg/m³ |
| `runs.history_only.station_adjustment[]` | number | 各提前时长的站点区间独立校准扩大量，μg/m³ |
| `runs.history_only.city_adjustment` | array | 各提前时长的城市均值区间独立校准扩大量，μg/m³ |
| `runs.history_only.city_adjustment[]` | number | 各提前时长的城市均值区间独立校准扩大量，μg/m³ |
| `runs.history_only.city_calibration_hours` | array | 城市均值各提前时长有效校准起点小时数 |
| `runs.history_only.city_calibration_hours[]` | integer | 城市均值各提前时长有效校准起点小时数 |
| `runs.history_only.best_epoch` | integer | 按模型选择期指标选出的轮次 |
| `runs.history_only.epochs` | array | 实际训练各轮记录 |
| `runs.history_only.epochs[]` | object | 实际训练各轮记录 |
| `runs.history_only.epochs[].epoch` | integer | 训练轮次序号 |
| `runs.history_only.epochs[].loss` | number | 训练目标函数平均值 |
| `runs.history_only.epochs[].selection_h6_rmse` | number | 模型选择期六小时 RMSE，μg/m³ |
| `runs.history_only.epochs[].seconds` | number | 本轮或整个实验耗时，秒 |
| `runs.future_weather` | object | 融合未来天气的对比实验，结构与 history_only 一致 |
| `runs.future_weather.selection` | object | 模型选择期或选择指标 |
| `runs.future_weather.selection.by_horizon` | array | 按提前小时分组的指标列表 |
| `runs.future_weather.selection.by_horizon[]` | object | 按提前小时分组的指标列表 |
| `runs.future_weather.selection.by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.selection.by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.selection.by_horizon[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.selection.by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.selection.by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.selection.by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.selection.by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.selection.city_by_horizon` | array | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.future_weather.selection.city_by_horizon[]` | object | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.future_weather.selection.city_by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.selection.city_by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.selection.city_by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.selection.city_by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.selection.city_by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.selection.city_by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.selection.regimes` | object | 按实测浓度或变化幅度划分的离线测试指标 |
| `runs.future_weather.selection.regimes.pm_lt35` | array | 目标PM2.5小于35 μg/m³的分组 |
| `runs.future_weather.selection.regimes.pm_lt35[]` | object | 目标PM2.5小于35 μg/m³的分组 |
| `runs.future_weather.selection.regimes.pm_lt35[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.selection.regimes.pm_lt35[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.selection.regimes.pm_lt35[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.selection.regimes.pm_lt35[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.selection.regimes.pm_lt35[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.selection.regimes.pm_lt35[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.selection.regimes.pm_lt35[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.selection.regimes.pm_35_75` | array | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.future_weather.selection.regimes.pm_35_75[]` | object | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.future_weather.selection.regimes.pm_35_75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.selection.regimes.pm_35_75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.selection.regimes.pm_35_75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.selection.regimes.pm_35_75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.selection.regimes.pm_35_75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.selection.regimes.pm_35_75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.selection.regimes.pm_35_75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.selection.regimes.pm_ge75` | array | 目标PM2.5至少75 μg/m³的分组 |
| `runs.future_weather.selection.regimes.pm_ge75[]` | object | 目标PM2.5至少75 μg/m³的分组 |
| `runs.future_weather.selection.regimes.pm_ge75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.selection.regimes.pm_ge75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.selection.regimes.pm_ge75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.selection.regimes.pm_ge75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.selection.regimes.pm_ge75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.selection.regimes.pm_ge75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.selection.regimes.pm_ge75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.selection.regimes.abrupt_ge20` | array | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.future_weather.selection.regimes.abrupt_ge20[]` | object | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.future_weather.selection.regimes.abrupt_ge20[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.selection.regimes.abrupt_ge20[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.selection.regimes.abrupt_ge20[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.selection.regimes.abrupt_ge20[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.selection.regimes.abrupt_ge20[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.selection.regimes.abrupt_ge20[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.selection.regimes.abrupt_ge20[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.test` | object | 测试期或测试指标 |
| `runs.future_weather.test.by_horizon` | array | 按提前小时分组的指标列表 |
| `runs.future_weather.test.by_horizon[]` | object | 按提前小时分组的指标列表 |
| `runs.future_weather.test.by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.test.by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.test.by_horizon[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.test.by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.test.by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.test.by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.test.by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.test.city_by_horizon` | array | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.future_weather.test.city_by_horizon[]` | object | 在完整共同队列上按北京均值评估的各时长指标 |
| `runs.future_weather.test.city_by_horizon[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.test.city_by_horizon[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.test.city_by_horizon[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.test.city_by_horizon[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.test.city_by_horizon[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.test.city_by_horizon[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.test.regimes` | object | 按实测浓度或变化幅度划分的离线测试指标 |
| `runs.future_weather.test.regimes.pm_lt35` | array | 目标PM2.5小于35 μg/m³的分组 |
| `runs.future_weather.test.regimes.pm_lt35[]` | object | 目标PM2.5小于35 μg/m³的分组 |
| `runs.future_weather.test.regimes.pm_lt35[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.test.regimes.pm_lt35[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.test.regimes.pm_lt35[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.test.regimes.pm_lt35[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.test.regimes.pm_lt35[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.test.regimes.pm_lt35[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.test.regimes.pm_lt35[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.test.regimes.pm_35_75` | array | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.future_weather.test.regimes.pm_35_75[]` | object | 目标PM2.5在35至不足75 μg/m³的分组 |
| `runs.future_weather.test.regimes.pm_35_75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.test.regimes.pm_35_75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.test.regimes.pm_35_75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.test.regimes.pm_35_75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.test.regimes.pm_35_75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.test.regimes.pm_35_75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.test.regimes.pm_35_75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.test.regimes.pm_ge75` | array | 目标PM2.5至少75 μg/m³的分组 |
| `runs.future_weather.test.regimes.pm_ge75[]` | object | 目标PM2.5至少75 μg/m³的分组 |
| `runs.future_weather.test.regimes.pm_ge75[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.test.regimes.pm_ge75[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.test.regimes.pm_ge75[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.test.regimes.pm_ge75[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.test.regimes.pm_ge75[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.test.regimes.pm_ge75[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.test.regimes.pm_ge75[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.test.regimes.abrupt_ge20` | array | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.future_weather.test.regimes.abrupt_ge20[]` | object | 实测与起点浓度差的绝对值至少20 μg/m³的分组 |
| `runs.future_weather.test.regimes.abrupt_ge20[].horizon` | integer | 提前小时；实时接口表示距发布时间所在整点的未来小时 |
| `runs.future_weather.test.regimes.abrupt_ge20[].n` | integer | 参与当前统计的有效样本数 |
| `runs.future_weather.test.regimes.abrupt_ge20[].mae` | number | 平均绝对误差，μg/m³ |
| `runs.future_weather.test.regimes.abrupt_ge20[].rmse` | number | 均方根误差，μg/m³ |
| `runs.future_weather.test.regimes.abrupt_ge20[].baseline_rmse` | number | 同样本持续性基线的 RMSE，μg/m³ |
| `runs.future_weather.test.regimes.abrupt_ge20[].coverage` | number | 已有实测且保存区间的样本中，实测落入区间的比例，0—1 |
| `runs.future_weather.test.regimes.abrupt_ge20[].mean_width` | number | 区间上限减下限的平均值，μg/m³ |
| `runs.future_weather.station_adjustment` | array | 各提前时长的站点区间独立校准扩大量，μg/m³ |
| `runs.future_weather.station_adjustment[]` | number | 各提前时长的站点区间独立校准扩大量，μg/m³ |
| `runs.future_weather.city_adjustment` | array | 各提前时长的城市均值区间独立校准扩大量，μg/m³ |
| `runs.future_weather.city_adjustment[]` | number | 各提前时长的城市均值区间独立校准扩大量，μg/m³ |
| `runs.future_weather.city_calibration_hours` | array | 城市均值各提前时长有效校准起点小时数 |
| `runs.future_weather.city_calibration_hours[]` | integer | 城市均值各提前时长有效校准起点小时数 |
| `runs.future_weather.best_epoch` | integer | 按模型选择期指标选出的轮次 |
| `runs.future_weather.epochs` | array | 实际训练各轮记录 |
| `runs.future_weather.epochs[]` | object | 实际训练各轮记录 |
| `runs.future_weather.epochs[].epoch` | integer | 训练轮次序号 |
| `runs.future_weather.epochs[].loss` | number | 训练目标函数平均值 |
| `runs.future_weather.epochs[].selection_h6_rmse` | number | 模型选择期六小时 RMSE，μg/m³ |
| `runs.future_weather.epochs[].seconds` | number | 本轮或整个实验耗时，秒 |
| `runs.future_weather.worst_test_h6` | array | 未来天气模型在离线六小时测试中的最差样本列表 |
| `runs.future_weather.worst_test_h6[]` | object | 未来天气模型在离线六小时测试中的最差样本列表 |
| `runs.future_weather.worst_test_h6[].station_id` | string | 空气质量站点编号；mean 表示北京覆盖站点均值 |
| `runs.future_weather.worst_test_h6[].origin` | string | 最后可用实测的预测起点，北京时间 |
| `runs.future_weather.worst_test_h6[].prediction` | number | 模型预测 PM2.5；v3 为中位数，μg/m³ |
| `runs.future_weather.worst_test_h6[].actual` | number | 目标时刻实测 PM2.5，未到达为 null，μg/m³ |
| `runs.future_weather.worst_test_h6[].absolute_error` | number | 单个样本绝对误差，μg/m³ |
| `interval_note` | string | 区间校准方法与适用边界 |
| `weather_note` | string | 天气来源、可用性或历史与实时差异的说明 |
| `checkpoint_sha256` | string | 模型权重原始字节的 SHA-256 |
| `gpu` | object | 显卡型号或 GPU 执行证据对象，按类型区分 |
| `gpu.device` | string | 报告记录的执行设备名称 |
| `gpu.pytorch` | string | 报告记录的 PyTorch 版本 |
| `gpu.peak_util_percent` | number | 采样到的最高 GPU 利用率，% |
| `gpu.peak_torch_mib` | number | PyTorch 峰值已分配显存，MiB |
| `gpu.seconds` | number | 本轮或整个实验耗时，秒 |

尚无报告时为 `{"ready":false,"message":"未来天气模型正在准备，当前已发布模型继续工作"}`。

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/live/model`，状态 `200`。

```json
{
  "ready": true,
  "completed_at": "2026-10-22T22:51:48.812055+08:00",
  "model": "forecast_tcn9",
  "data": {
    "start": "2024-01-01T00",
    "hours": 17544,
    "stations_metadata": [
      {
        "station_id": "1001A",
        "city_id": "beijing",
        "city_name": "北京",
        "name": "万寿西宫"
      }
    ],
    "cities": [
      "beijing"
    ]
  },
  "samples": {
    "train": 382388,
    "selection": 34041,
    "calibration": 34656,
    "test": 193411
  },
  "runs": {
    "history_only": {
      "selection": {
        "by_horizon": [
          {
            "horizon": 1,
            "n": 33413,
            "mae": 3.745509147644043,
            "rmse": 7.701976776123047
          }
        ],
        "city_by_horizon": [
          {
            "horizon": 1,
            "n": 1348,
            "rmse": 4.935299858628748,
            "baseline_rmse": 3.876408158567322
          }
        ],
        "regimes": {
          "pm_lt35": [
            {
              "horizon": 1,
              "n": 23779,
              "mae": 2.2027997970581055,
              "rmse": 4.331204414367676
            }
          ],
          "pm_35_75": [
            {
              "horizon": 1,
              "n": 6345,
              "mae": 4.600905418395996,
              "rmse": 6.528672218322754
            }
          ],
          "pm_ge75": [
            {
              "horizon": 1,
              "n": 3289,
              "mae": 13.248881340026855,
              "rmse": 19.615873336791992
            }
          ],
          "abrupt_ge20": [
            {
              "horizon": 1,
              "n": 529,
              "mae": 26.17151641845703,
              "rmse": 29.199237823486328
            }
          ]
        }
      },
      "test": {
        "by_horizon": [
          {
            "horizon": 1,
            "n": 189203,
            "mae": 3.532501697540283,
            "rmse": 6.551501750946045
          }
        ],
        "city_by_horizon": [
          {
            "horizon": 1,
            "n": 7872,
            "rmse": 4.144722978904604,
            "baseline_rmse": 3.487517913591262
          }
        ],
        "regimes": {
          "pm_lt35": [
            {
              "horizon": 1,
              "n": 139265,
              "mae": 2.5422589778900146,
              "rmse": 4.456250190734863
            }
          ],
          "pm_35_75": [
            {
              "horizon": 1,
              "n": 37736,
              "mae": 4.890600204467773,
              "rmse": 7.328341484069824
            }
          ],
          "pm_ge75": [
            {
              "horizon": 1,
              "n": 12202,
              "mae": 10.63436508178711,
              "rmse": 16.51704216003418
            }
          ],
          "abrupt_ge20": [
            {
              "horizon": 1,
              "n": 3161,
              "mae": 26.645137786865234,
              "rmse": 29.80406951904297
            }
          ]
        }
      },
      "station_adjustment": [
        0.0
      ],
      "city_adjustment": [
        0.0
      ]
    },
    "future_weather": {
      "selection": {
        "by_horizon": [
          {
            "horizon": 1,
            "n": 33413,
            "mae": 3.776501178741455,
            "rmse": 7.699659824371338
          }
        ],
        "city_by_horizon": [
          {
            "horizon": 1,
            "n": 1348,
            "rmse": 4.908780861112489,
            "baseline_rmse": 3.876408158567322
          }
        ],
        "regimes": {
          "pm_lt35": [
            {
              "horizon": 1,
              "n": 23779,
              "mae": 2.2212610244750977,
              "rmse": 4.290571212768555
            }
          ],
          "pm_35_75": [
            {
              "horizon": 1,
              "n": 6345,
              "mae": 4.680659770965576,
              "rmse": 6.591731071472168
            }
          ],
          "pm_ge75": [
            {
              "horizon": 1,
              "n": 3289,
              "mae": 13.276399612426758,
              "rmse": 19.630502700805664
            }
          ],
          "abrupt_ge20": [
            {
              "horizon": 1,
              "n": 529,
              "mae": 25.73575210571289,
              "rmse": 28.78270721435547
            }
          ]
        }
      },
      "test": {
        "by_horizon": [
          {
            "horizon": 1,
            "n": 189203,
            "mae": 3.623863697052002,
            "rmse": 6.291281223297119
          }
        ],
        "city_by_horizon": [
          {
            "horizon": 1,
            "n": 7872,
            "rmse": 3.813408254197664,
            "baseline_rmse": 3.487517913591262
          }
        ],
        "regimes": {
          "pm_lt35": [
            {
              "horizon": 1,
              "n": 139265,
              "mae": 2.7428886890411377,
              "rmse": 4.435115337371826
            }
          ],
          "pm_35_75": [
            {
              "horizon": 1,
              "n": 37736,
              "mae": 4.960965156555176,
              "rmse": 7.318606853485107
            }
          ],
          "pm_ge75": [
            {
              "horizon": 1,
              "n": 12202,
              "mae": 9.543557167053223,
              "rmse": 14.952539443969727
            }
          ],
          "abrupt_ge20": [
            {
              "horizon": 1,
              "n": 3161,
              "mae": 25.16621208190918,
              "rmse": 28.29145050048828
            }
          ]
        }
      },
      "station_adjustment": [
        0.43167686462402344
      ],
      "city_adjustment": [
        0.0
      ]
    }
  },
  "interval_note": "80% nominal CQR; Nov-Dec 2024 calibration is separate from model selection and 2025 test. Time/station dependence and domain shifts prevent a universal coverage guarantee."
}
```

## GET /api/system

无参数。HDFS 是 generated_at 时刻的缓存快照；checked_at 是本次本地文件核对时间。Hadoop/Python 等版本若未写入任何报告，返回 null。版本来源见 version_sources。缺少或损坏的证据列入 warnings，仍返回200。

读取或写入：reports/hdfs_inventory.json、reports/*.json、明确列出的本地产物的 stat 元数据；不执行外部命令。

### 参数

无。

### 返回字段

| 字段路径 | JSON类型 | 含义与单位 |
| --- | --- | --- |
| `checked_at` | string | 接口读取本地证据与元数据的时刻，北京时间 |
| `hdfs_inventory` | object | 离线生成的 HDFS 盘点快照；未生成或损坏时为 null |
| `hdfs_inventory.generated_at` | string | HDFS 盘点完成时刻，北京时间 |
| `hdfs_inventory.hdfs_root` | string | 配置中的 HDFS 项目根路径 |
| `hdfs_inventory.command` | string | 生成盘点所用的只读命令名 |
| `hdfs_inventory.complete` | boolean | 本次六个目录计数是否全部成功 |
| `hdfs_inventory.entries` | array | 按 HDFS 子目录组织的盘点条目 |
| `hdfs_inventory.entries[]` | object | 按 HDFS 子目录组织的盘点条目 |
| `hdfs_inventory.entries[].name` | string | 城市、站点、变量或来源的显示名称 |
| `hdfs_inventory.entries[].path` | string | 项目内相对文件路径或 HDFS 完整路径 |
| `hdfs_inventory.entries[].directories` | integer | HDFS 子树目录数 |
| `hdfs_inventory.entries[].files` | integer | HDFS 子树文件数 |
| `hdfs_inventory.entries[].bytes` | integer | 逻辑文件大小，byte；失败或不存在时为 null |
| `hdfs_inventory.entries[].status` | string | 状态字符串；健康检查为 ok，盘点条目为 ok/error |
| `hdfs_inventory.entries[].error` | null | 失败原因，成功时为 null |
| `hdfs_inventory.note` | string | 统计、来源或使用边界的文字说明 |
| `versions` | object | 已有报告记录的组件版本/显卡名，未记录为 null |
| `versions.hadoop` | null | 报告中的 Hadoop 版本；目前无记录时为 null |
| `versions.spark` | string | 报告中的 Spark 版本 |
| `versions.python` | null | 报告中的 Python 版本；目前无记录时为 null |
| `versions.pytorch` | string | 报告记录的 PyTorch 版本 |
| `versions.gpu` | string | 显卡型号或 GPU 执行证据对象，按类型区分 |
| `version_sources` | object | 每个版本的报告路径和 JSON 字段位置，未记录为 null |
| `version_sources.hadoop` | null | 报告中的 Hadoop 版本；目前无记录时为 null |
| `version_sources.spark` | object | 报告中的 Spark 版本 |
| `version_sources.spark.report` | string | 摘要或版本证据的项目内报告路径 |
| `version_sources.spark.field` | string | 证据值在报告中的 JSON 字段路径 |
| `version_sources.python` | null | 报告中的 Python 版本；目前无记录时为 null |
| `version_sources.pytorch` | object | 报告记录的 PyTorch 版本 |
| `version_sources.pytorch.report` | string | 摘要或版本证据的项目内报告路径 |
| `version_sources.pytorch.field` | string | 证据值在报告中的 JSON 字段路径 |
| `version_sources.gpu` | object | 显卡型号或 GPU 执行证据对象，按类型区分 |
| `version_sources.gpu.report` | string | 摘要或版本证据的项目内报告路径 |
| `version_sources.gpu.field` | string | 证据值在报告中的 JSON 字段路径 |
| `generations` | object | city、station、forecast 三代数据规模摘要 |
| `generations.city` | object | 所选城市 ID，或系统证据中的城市代摘要 |
| `generations.city.report` | string | 摘要或版本证据的项目内报告路径 |
| `generations.city.summary` | object | 数据规模或误差的摘要对象 |
| `generations.city.summary.spark_version` | string | 报告记录的 Spark 版本 |
| `generations.city.summary.spark_master` | string | Spark 运行模式 |
| `generations.city.summary.start_date` | string | 数据起始日期 |
| `generations.city.summary.end_date` | string | 数据结束日期 |
| `generations.city.summary.timezone` | string | 时间所属时区 |
| `generations.city.summary.cities` | array | 城市目录或城市 ID 列表，按实际结构读取 |
| `generations.city.summary.cities[]` | object | 城市目录或城市 ID 列表，按实际结构读取 |
| `generations.city.summary.cities[].id` | string | 城市 ID |
| `generations.city.summary.cities[].name` | string | 城市、站点、变量或来源的显示名称 |
| `generations.city.summary.cities[].latitude` | number | 纬度，度 |
| `generations.city.summary.cities[].longitude` | number | 经度，度 |
| `generations.city.summary.panel_rows` | integer | 城市×小时完整网格行数 |
| `generations.city.summary.distinct_city_hour_keys` | integer | 城市×小时唯一键数量 |
| `generations.city.summary.beijing_feature_rows` | integer | 北京小时特征行数 |
| `generations.city.summary.pm25_valid_hours_all_cities` | integer | 全部城市 PM2.5 有效小时数 |
| `generations.city.summary.raw_bytes` | integer | 原始文件逻辑字节数，byte |
| `generations.city.summary.download_summary` | object | 下载成功/缺失情况，按来源分组 |
| `generations.city.summary.download_summary.air` | object | 空气质量来源摘要 |
| `generations.city.summary.download_summary.air.missing` | integer | 缺失文件数量 |
| `generations.city.summary.download_summary.air.ok` | integer | 成功文件数量 |
| `generations.city.summary.download_summary.weather` | object | 天气来源或天气摘要 |
| `generations.city.summary.download_summary.weather.ok` | integer | 成功文件数量 |
| `generations.city.summary.source_missing_dates` | array | 原来源缺少的日期列表 |
| `generations.city.summary.source_missing_dates[]` | string | 原来源缺少的日期列表 |
| `generations.station` | object | 单个站点元数据，或系统证据中的站点代摘要 |
| `generations.station.report` | string | 摘要或版本证据的项目内报告路径 |
| `generations.station.summary` | object | 数据规模或误差的摘要对象 |
| `generations.station.summary.stations` | integer | 站点目录或站点数量，按类型区分 |
| `generations.station.summary.start` | string | 起始日期或时间（上下文决定） |
| `generations.station.summary.end` | string | 结束日期或时间（上下文决定） |
| `generations.station.summary.grid_hours` | integer | 站点×小时完整网格行数 |
| `generations.station.summary.valid_pm25` | integer | 有效 PM2.5 观测数 |
| `generations.station.summary.source_days` | integer | 实际有原始档案的日期数 |
| `generations.station.summary.expected_days` | integer | 预期日期总数 |
| `generations.station.summary.feature_count` | integer | 输入特征数量 |
| `generations.station.summary.weather_history_hours` | integer | 过去天气窗口长度，小时 |
| `generations.station.summary.raw_archive_bytes` | integer | 站点全国原始档案字节数，byte |
| `generations.station.summary.source_file_count` | integer | 全国档案原始文件数 |
| `generations.station.summary.web_database_bytes` | integer | 发布的站点 SQLite 字节数，byte |
| `generations.station.summary.indexed_predictions` | object | 已导入查询库的各模型/提前时长预测行数 |
| `generations.station.summary.indexed_predictions.*` | integer | 对应模型及提前小时已入库的预测行数 |
| `generations.station.summary.splits` | object | 按时间划分的训练、选择、校准和测试边界 |
| `generations.station.summary.splits.train_end` | integer | 训练期最后年份 |
| `generations.station.summary.splits.validation` | integer | 验证期或验证指标 |
| `generations.station.summary.splits.test` | integer | 测试期或测试指标 |
| `generations.station.summary.hdfs` | string | 相关数据在 HDFS 中的路径 |
| `generations.station.summary.spark_version` | string | 报告记录的 Spark 版本 |
| `generations.forecast` | object | 未来天气预测代的数据规模摘要 |
| `generations.forecast.report` | string | 摘要或版本证据的项目内报告路径 |
| `generations.forecast.summary` | object | 数据规模或误差的摘要对象 |
| `generations.forecast.summary.start` | string | 起始日期或时间（上下文决定） |
| `generations.forecast.summary.hours` | integer | 小时网格长度或所选窗口长度，小时 |
| `generations.forecast.summary.cities` | array | 城市目录或城市 ID 列表，按实际结构读取 |
| `generations.forecast.summary.cities[]` | string | 城市目录或城市 ID 列表，按实际结构读取 |
| `generations.forecast.summary.sequence_columns` | array | 历史输入通道的有序字段列表 |
| `generations.forecast.summary.sequence_columns[]` | string | 历史输入通道的有序字段列表 |
| `generations.forecast.summary.weather_columns` | array | 未来天气通道的有序字段名 |
| `generations.forecast.summary.weather_columns[]` | string | 未来天气通道的有序字段名 |
| `generations.forecast.summary.weather_model` | string | 天气模型标识 |
| `generations.forecast.summary.weather_lead_hours` | integer | 天气预测相对其有效时刻的固定提前量，小时 |
| `generations.forecast.summary.weather_valid_hours` | integer | 可用城市×天气小时记录数 |
| `generations.forecast.summary.splits` | object | 按时间划分的训练、选择、校准和测试边界 |
| `generations.forecast.summary.splits.train` | string | 训练期或训练样本数 |
| `generations.forecast.summary.splits.selection` | string | 模型选择期或选择指标 |
| `generations.forecast.summary.splits.calibration` | string | 独立区间校准期或样本数 |
| `generations.forecast.summary.splits.test` | string | 测试期或测试指标 |
| `generations.forecast.summary.hdfs` | string | 相关数据在 HDFS 中的路径 |
| `generations.forecast.summary.spark_version` | string | 报告记录的 Spark 版本 |
| `artifacts` | array | 各流水线阶段明确列出的本地产物清单 |
| `artifacts[]` | object | 各流水线阶段明确列出的本地产物清单 |
| `artifacts[].pipeline` | string | 产物所属流水线 |
| `artifacts[].stage` | string | 产物在流水线中的用途 |
| `artifacts[].path` | string | 项目内相对文件路径或 HDFS 完整路径 |
| `artifacts[].exists` | boolean | 本地产物是否存在且可取得元数据 |
| `artifacts[].bytes` | integer | 逻辑文件大小，byte；失败或不存在时为 null |
| `artifacts[].modified_at` | string | 本地产物最后修改时间，北京时间 |
| `warnings` | array | 缺失或损坏的证据文件及中文说明 |
| `note` | string | 统计、来源或使用边界的文字说明 |

### 错误与状态

- 正常为200；刷新接口为202。可选证据不足通过 ready、null 或 warnings 表示。

### 实际响应节选

请求：`GET /api/system`，状态 `200`。

```json
{
  "checked_at": "2026-10-23T00:11:43.956250+08:00",
  "hdfs_inventory": {
    "generated_at": "2026-10-23T00:04:56.062858+08:00",
    "hdfs_root": "hdfs://localhost:9000/user/hadoop/pm25_beijing/2015_2025",
    "command": "hdfs dfs -count",
    "complete": true
  },
  "versions": {
    "hadoop": null,
    "spark": "3.5.8",
    "python": null,
    "pytorch": "2.14.1+cu126"
  },
  "version_sources": {
    "hadoop": null,
    "spark": {
      "report": "reports/forecast_model_results.json",
      "field": "data.spark_version"
    },
    "python": null,
    "pytorch": {
      "report": "reports/forecast_model_results.json",
      "field": "gpu.pytorch"
    }
  },
  "generations": {
    "city": {
      "report": "reports/data_summary.json",
      "summary": {
        "spark_version": "3.5.8",
        "spark_master": "local[4]",
        "start_date": "2015-01-01",
        "end_date": "2025-12-31"
      }
    },
    "station": {
      "report": "reports/station_summary.json",
      "summary": {
        "stations": 81,
        "start": "2022-01-01",
        "end": "2025-12-31",
        "grid_hours": 2840184
      }
    },
    "forecast": {
      "report": "reports/forecast_training_data.json",
      "summary": {
        "start": "2024-01-01T00",
        "hours": 17544,
        "cities": [
          "beijing"
        ],
        "sequence_columns": [
          "pm25"
        ]
      }
    }
  },
  "artifacts": [
    {
      "pipeline": "city",
      "stage": "原始来源清单",
      "path": "data/manifests/download_manifest.json",
      "exists": true
    }
  ],
  "warnings": []
}
```

## 网页与自动文档路由

| 方法/路径 | 返回及来源 | 错误 |
| --- | --- | --- |
| `GET /` | `frontend/dist/index.html`，HTML网页入口 | 构建目录存在时注册；产物被移走后文件响应可能失败 |
| `GET /region.geojson` | `frontend/dist/region.geojson`，application/geo+json；GeoJSON FeatureCollection/Feature/geometry/properties 为地图边界数据 | 文件不存在时文件响应失败 |
| `GET /favicon.svg` | `frontend/dist/favicon.svg`，image/svg+xml | 文件不存在时文件响应失败 |
| `GET /assets/{path}` | `frontend/dist/assets/`下构建资源，文件名由已有前端构建确定 | 404：资源不存在 |
| `GET /openapi.json` | FastAPI生成的接口结构，JSON | 无业务参数 |
| `GET /docs`、`GET /redoc`、`GET /docs/oauth2-redirect` | FastAPI自动文档与其回调页，HTML | 无业务参数 |

以上静态路由不返回业务 JSON 字段。`frontend/dist` 不存在时三个显式网页路由及 assets 挂载不注册；本次没有修改前端。

## HDFS 盘点更新

在 WSL 项目根目录执行：

```bash
/home/hadoop/venvs/pm25/bin/python scripts/hdfs_inventory.py
```

该脚本对配置根目录下 raw、processed、models、stations_v2、live_v1、forecast_v3 分别执行 `hdfs dfs -count`，原子保存报告。逻辑字节数不乘副本数。任一目录失败时保留 error 与 null 计数，并以非零退出码结束；API不会代替脚本重跑。


### 静态路由实际调用节选

下列响应来自已运行的本地服务；摘录只用于确认格式。

`GET /` → `200`，`text/html; charset=utf-8`，正文 `699` 字节。

```text
<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="theme-color" content="#176753"><meta name="description" content="基于北京及周边五城十
```

`GET /region.geojson` → `200`，`application/geo+json`，正文 `133115` 字节。

```text
{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"adcode":110000,"name":"北京市","center":[116.405285,39.904989],"centroid":[116.41995,40.18994],"childrenNum":16,"level":"province","acroutes":[100000]
```

`GET /favicon.svg` → `200`，`image/svg+xml`，正文 `279` 字节。

```text
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="10" fill="#176e59"/><g fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"><path d="M9 16h17c6 0 5-8 0-8-2 0-3 
```
