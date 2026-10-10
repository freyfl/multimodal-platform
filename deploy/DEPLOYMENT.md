# 火山引擎 ECS 部署指南

## 交付边界

目标架构为 ECS / VPC / TOS / 方舟 Responses 与多模态 Embeddings，并在同一台 ECS 通过 Docker Compose 部署开源 MySQL 8.4、Milvus Standalone、etcd 和 MinIO。真实 TOS endpoint、bucket 和方舟凭证尚未提供，本机容器也未在目标 ECS 实测，本文不是接入成功报告。精确 Seed 模型权限与视频能力必须在实际账号验证；不可用时报告阻塞，不换模型。

前后端接口有破坏性变更，必须成套升级。安装、启动、停止、打包继续使用 Shell；默认单 FastAPI worker，不引入消息队列、Redis、Kubernetes 或应用内日志云 SDK。

## 资源与网络

默认北京地域，实际资源以各产品支持地域为准；跨地域时重新验证路由、延迟和费用。

| 资源 | 准备要求 |
|---|---|
| ECS | Linux、Python 3.11、Node.js 22.12+、npm、Docker Engine、Docker Compose V2、Bash、curl、tar、FFmpeg/FFprobe；预留容器镜像、数据库、向量、私有帧、临时解码、日志和构建空间 |
| VPC | ECS 对 TOS 和方舟保持 HTTPS 出站；安全组只开放业务入口，不开放数据库端口 |
| 本机 MySQL | Compose 固定 `mysql:8.4.6`，初始化独立数据库及应用账号；`127.0.0.1:3306`，命名卷持久化 |
| 本机 Milvus | Compose 固定 `milvusdb/milvus:v2.6.23` Standalone，并部署兼容的 etcd 与 MinIO；`127.0.0.1:19530/9091`，命名卷持久化 |
| TOS | 私有 bucket、限定前缀权限；扫描/读取，按导入需求授权上传/删除临时对象；endpoint 从控制台获取 |
| 方舟 | 北京地域、指定两个模型的调用权限、额度及 HTTPS 出站网络 |

ECS 到 TOS、方舟需要 HTTPS 连通；方舟和浏览器必须能访问有效期内的 TOS 签名 HTTPS URL，不能使用只对 ECS 可见的私网地址。私有桶不需要公共读。视频预览需支持 HEAD、Range、206、416；直接跨域访问时在 TOS 按业务域名配置 CORS 和必要响应头暴露。

生产入口由运维配置 HTTPS。前端静态服务默认监听 `3000`，通过 `/api/` 代理到本机 `127.0.0.1:8000`；MySQL、Milvus 和 Milvus 管理端口在 Compose 中仅绑定 `127.0.0.1`，不得改成公网监听。本机连接不启用 TLS；TOS 和方舟 HTTPS 仍必须验证证书。

这是单机部署：ECS 或本地磁盘故障会同时影响应用、元数据和向量检索。生产使用前必须制定 ECS 云盘快照、MySQL 逻辑备份、Milvus 数据卷备份及恢复演练；Compose 命名卷不是备份。

## 安装与配置

在已验证发布包解压后的项目根目录执行：

```bash
PYTHON_BIN=python3.11 bash deploy/install.sh
```

脚本检查 Python 3.11、Node 22.12+、Docker Compose V2 和 FFmpeg/FFprobe 可执行性，创建 `backend/venv`，安装 Python 依赖（含 Pillow），并执行 `npm ci --include=dev` 和生产构建。FFmpeg 是宿主机系统依赖，例如 Debian/Ubuntu 使用组织批准的软件源安装 `ffmpeg` 包；pip 不提供该依赖，也无需修改数据库 Compose 镜像。即使包内有 `dist` 也重新构建；构建失败立即退出。已有虚拟环境不是 Python 3.11 时拒绝继续，由运维显式处理，不自动删除。

npm 默认 `https://registry.npmjs.org`，可设置 `NPM_REGISTRY` 为已授权的火山制品仓库。私有仓库凭证在机器级安全注入，不写到项目 `.npmrc` 或命令中的带密码 URL。`PIP_INDEX_URL` 可按组织策略注入。需要标准源完全生效时也应检查 lockfile 中 `resolved` 地址；更换锁定源由前端维护者审查更新，安装脚本不改 lockfile。

安装脚本不读取、不创建、不覆盖 `backend/.env`，不启动容器，也不自动运行初始化、迁移或清理。以最新 `backend/.env.example` 为模板，在目标 ECS 上由运维安全注入实际配置；已有文件需人工核对，不能直接覆盖。模板中的应用、MySQL root 与 MinIO 凭证为空，不能直接启动。

**配置读取必须显式选择：**

- 默认使用项目内 `backend/.env`；也可将 `APP_ENV_FILE` 设置为其他绝对路径。
- `start.sh` 和 `infra.sh` 拒绝相对路径及符号链接。应用由 dotenv 解析器读取，Compose 通过 `--env-file` 读取；Shell 不执行或 `source` 文件内容。
- 进程环境中已有变量优先于 dotenv，排查时注意旧环境残留。

```bash
# 在项目根目录，运维已完成配置且限制文件访问权限后
APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/start.sh --daemon
```

不要将 JWT、数据库密码、API Key、签名 URL 或用户级配置写入日志、截图、迁移报告、发布包。JWT 使用独立高强度随机密钥，例如 `openssl rand -hex 32`；管理员密码无默认值，生产按组织策略关闭开放注册。

## 精确环境合同

全部字段以 `backend/.env.example` 和 `backend/app/config.py` 为准。以下值不替换为其他模型或旧维度。

```dotenv
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_TAG_MODEL=doubao-seed-2-1-lite-260915
ARK_EMBEDDING_MODEL=doubao-embedding-vision-251215
EMBEDDING_DIMENSION=1024
EMBEDDING_CORPUS_INSTRUCTION_VERSION=road-scene-corpus-v1
EMBEDDING_QUERY_INSTRUCTION_VERSION=road-scene-query-v1
TEXT_SEARCH_MIN_SCORE=0
MILVUS_COLLECTION=media_vectors_v2
MILVUS_URI=http://127.0.0.1:19530
MILVUS_DB_NAME=default
MILVUS_AUTH_ENABLED=false
MILVUS_SECURE=false
MILVUS_METRIC_TYPE=COSINE
MILVUS_INDEX_TYPE=HNSW
MILVUS_HNSW_M=16
MILVUS_HNSW_EF_CONSTRUCTION=200
MILVUS_SEARCH_EF=100
MILVUS_CONSISTENCY_LEVEL=Strong
MYSQL_PORT=3306
MYSQL_HOST=127.0.0.1
MYSQL_DATABASE=multimodal_platform
MYSQL_SSL_ENABLED=false
TOS_REGION=cn-beijing
```

| 配置族 | 连接和安全参数 |
|---|---|
| TOS | 必填 `TOS_ACCESS_KEY_ID`、`TOS_ACCESS_KEY_SECRET`、`TOS_BUCKET_NAME`、`TOS_ENDPOINT`、`TOS_REGION`；可选 `TOS_SECURITY_TOKEN`、`TOS_CUSTOM_DOMAIN`；`TOS_SIGNED_URL_EXPIRES=3600` |
| 方舟 | `ARK_API_KEY`；`ARK_REQUEST_TIMEOUT=300`、`ARK_MAX_RETRIES=2`、`ARK_RETRY_BASE_DELAY=1`、`ARK_RETRY_MAX_DELAY=30`、`ARK_MAX_CONCURRENCY=5` |
| Milvus | 本机默认无认证：`MILVUS_AUTH_ENABLED=false`、`MILVUS_SECURE=false`；只有服务端启用认证时才配置 token 或用户密码 |
| MySQL | `MYSQL_USER`、`MYSQL_PASSWORD`；本机 `MYSQL_HOST=127.0.0.1`、`MYSQL_SSL_ENABLED=false`、`MYSQL_CONNECT_TIMEOUT=10` |
| 容器 | `INFRA_MYSQL_ROOT_PASSWORD`、`INFRA_MINIO_ROOT_USER`、`INFRA_MINIO_ROOT_PASSWORD` 必须设置为互不相同的强随机值 |
| 应用 | `JWT_SECRET_KEY`、`DEFAULT_ADMIN_PASSWORD`、`DEFAULT_ADMIN_USERNAME=admin`、`ALLOW_REGISTRATION`；`JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15`、`JWT_REFRESH_TOKEN_EXPIRE_DAYS=7` |
| 并发 | `MAX_CONCURRENT_TASKS=5`、`TASK_TIMEOUT=7200`、`CLOUD_IO_MAX_WORKERS=5` |

连接地址不嵌入凭证。MySQL 特殊字符密码由应用 URL 构造器处理，不手工拼接连接 URL。MinIO 仅供 Milvus 内部对象存储，不替代业务媒体所在的 TOS，也不映射宿主机端口。TOS 自定义域名仅在签名支持验证通过后启用，否则保留标准 endpoint。

标签仅调用 `POST /responses`，向量仅调用 `POST /embeddings/multimodal`；后者显式发送 `dimensions: 1024` 和 `encoding_format: float`。1024 为项目选择，不声称是模型默认维度。每条媒体一个稠密向量，不启用 sparse 或 multi embedding。

## 标注存储与资源

应用运行于宿主机，Compose 只管理数据库。由运维在持久化云盘上预建 `/var/lib/multimodal-platform/annotations`，设置 `ANNOTATION_STORAGE_DIR`；工作目录使用独立的 `/var/tmp/multimodal-platform/annotation-work`，设置 `ANNOTATION_TEMP_DIR`。两目录均须由应用账号所有、权限 `0700`，使用绝对真实路径，不得互相嵌套、使用符号链接或位于发布包内。升级切换目录时继续指向同一帧存储，禁止挂载缺失时回落到系统盘空目录；运维需核对实际挂载源、开机挂载顺序和可用空间。

不得将帧目录挂入 `frontend/dist`、`public`、Nginx `root/alias`、FastAPI 静态路由或公共桶；仅允许鉴权帧接口返回内容。启动设置 `umask 077`，新文件默认不向组/其他用户开放。路径与权限预检不能证明反向代理配置安全，发布验收仍须检查匿名访问及跨用户读取。

以下键按 T3 协调合同配置，需在 T3 最终代码落盘后复核实际消费；本次不修改 `backend/app`：

| 环境变量 | 默认值与含义 |
|---|---|
| `ANNOTATION_MAX_VIDEO_BYTES` | `2147483648`，单视频 2 GiB |
| `ANNOTATION_MAX_VIDEO_SECONDS` | `1800`，30 分钟 |
| `ANNOTATION_MAX_FRAME_PIXELS` | `33177600`，7680 × 4320 的 8K 像素预算 |
| `ANNOTATION_DECODE_TIMEOUT` | `300`，解码子进程秒数 |
| `ANNOTATION_DECODE_CONCURRENCY` | `1`，单 worker 解码并发 |

采样默认 1 秒/最多 60 帧，允许 1–60 秒/1–120 帧；每帧最多 200 对象，这些由请求/输出合同约束，不另造环境变量。工作盘容量应覆盖并发原视频下载和解码中间文件，独立设置磁盘配额及告警；私有帧盘监控容量、inode 与增长速度。FFmpeg 禁联网协议、实际 PTS、超限失败、超时/取消子进程回收及临时文件清理由 T3 运行时负责，不由部署预检代替。

`start.sh` 在启动容器前检查 FFmpeg/FFprobe、Pillow，并运行 `deploy/check_annotations.py`：只读解析显式配置（进程环境优先），拒绝缺失/非法资源值、目录重叠/包内路径/错误权限、超时低于 `7200/300` 或集合不为 `media_vectors_v2`。不会创建、改权限或清空目录。现有 `.env` 由运维逐项增补，不得覆盖；`TASK_TIMEOUT=7200`、`ARK_REQUEST_TIMEOUT=300` 不得回退。

## 初始化与启动

`start.sh` 会先执行 `infra.sh up`，等待四个容器健康后再启动应用。需要只启动基础设施或检查状态时：

```bash
APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/infra.sh up
APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/infra.sh status
APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/infra.sh logs milvus
```

首次启动 MySQL 容器会创建数据库和应用账号。命名卷已存在时，修改 `.env` 中的初始化密码不会修改数据库内账号；必须按 MySQL 运维流程显式轮换。基础设施健康后执行版本化 schema 初始化：

```bash
# 在项目根目录；必须显式传入配置，不能仅因为存在 .env 就假设会加载
(
  export APP_ENV_FILE="$(pwd)/backend/.env"
  cd backend
  ./venv/bin/python -m app.models.migrations
)
```

初始化入口支持重复执行和 schema 校验，不复制存量业务数据，不忽略结构冲突。首次全新部署可创建集合；已有系统本次标注升级必须保留并校验 `media_vectors_v2`，不重建向量。已有不兼容集合会拒绝向量请求，不能自动删除重建。应用首次启动可能执行 schema 与管理员检查，应在受控变更窗口进行。

```bash
APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/start.sh          # 前台等待
APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/start.sh --daemon # 或后台
bash deploy/stop.sh
APP_ENV_FILE="$(pwd)/backend/.env" bash deploy/infra.sh down # 可选
```

仅选择一种启动方式。`PORT` 可覆盖前端端口，后端固定本机 8000，`ALLOWED_ORIGINS` 按实际业务域名注入。日志为 `logs/backend.log`、`logs/frontend.log`；生产另配轮转，需要集中采集时使用火山 TLS 主机采集。

启动脚本以 Compose 健康检查确认本机基础设施，再以 `/api/system/health` 检查应用存活，不访问模型。`--daemon` 为 nohup 后台运行，不提供应用进程的系统重启自启。`stop.sh` 只停止应用；`infra.sh down` 停止容器但不带 `-v`，始终保留数据卷。脚本不提供卷清除命令。

后台任务为内存执行、MySQL 持久化状态；重启后遗留 running 任务应标为中断失败，通过幂等重导入继续。不能增加多个 worker 来扩展任务吞吐，也不能承诺重启自动恢复执行现场。

## 健康与联调

1. 应用存活：本机 `GET /api/system/health`；HTTP 可用不等于依赖就绪。
2. 依赖就绪：通过后端系统状态/就绪接口分别检查 TOS、MySQL、Milvus；缺配置或不可达必须报告不可用，不伪装空库。
3. 方舟实测：显式 `/api/settings/me/test-ark` 分别验证两个模型，可能消耗额度；一种成功不能表示全部成功。TOS 配置测试使用 `/api/settings/me/test-tos`。
4. 端到端：独立测试前缀和集合，验证私有图片/视频导入、标签、1024 维向量写入、三类检索、签名预览、视频拖动及导出。

常规探活不得反复调用模型。Seed 精确版本权限、Responses 视频输入和 embedding 图片 data URI 支持未实测前均为待验收；不通过自动换模型掩盖失败。

## 本次标注增量升级

1. 在授权变更窗口停止业务写入，备份 MySQL（含用户、媒体、标签、任务、标注版本/帧/结果集）、私有帧目录和配置，并保存 TOS 对象清单与 Milvus 一致性备份。保留 Compose 项目名 `multimodal-platform-infrastructure` 及四个命名卷，防止升级误连空卷。
2. 仅执行已审查的增量 schema 迁移，保留现有媒体、标签、任务、用户设置及 `media_vectors_v2`。旧媒体标记 `not_started`，不自动补标、不付费重跑、不重新导入或重建向量；本次不适用下方历史跨云迁移步骤。
3. 帧数据与 MySQL 引用按同一恢复点备份/恢复，保留所有者、权限及相对路径。新旧发布目录共享相同包外持久化帧目录；回退先核对 schema 向后兼容性，不自动降级 schema 或删除新增标注。
4. 重启验收核对升级前后媒体/标签/向量计数和样本读取、旧及新标注帧读取、失败帧可重试、无自动模型调用。未实际执行前不得报告通过。

清理仅通过所有者校验的媒体删除或经审查的版本回收流程；完整旧发布版本和失败重试所需成功帧不得当缓存删除。临时目录回收必须先确认任务/解码进程已停止，按任务工作目录预览目标，只删除无引用中间文件，绝不递归清理 `ANNOTATION_STORAGE_DIR`。本次不执行清理，也不提供全量删除命令。

## 历史跨云迁移与回退

以下仅用于另行授权的跨云/向量空间迁移，不适用于本次标注增量升级。

1. 停止旧系统业务写入或确定一致性快照，备份元数据及配置；源库只读，保留原资源。
2. 使用 TOS 官方迁移工具/控制台复制媒体，显式记录旧 bucket/prefix 到新 bucket/prefix 映射，核对对象及权限。
3. 将脱敏报告与真实导出文件分开。元数据导入先 dry-run，检查目标库、重复用户名/主键、对象映射、关联 ID；有冲突不 apply。
4. 显式导入本机 MySQL，保留用户密码哈希、UUID、人工标签及历史；不把旧 OSS/百炼凭证映射成 TOS/方舟凭证。旧名称只允许作为迁移输入映射或历史说明。
5. 旧向量不复制。目标媒体标记待重建，指定新 Milvus 集合，以方舟模型限量、可续跑地重新向量化；跳过条件须包含模型、维度、指令版本和集合身份。
6. 核验对象、媒体/标签数量、向量完成计数及失败报告，通过后前后端成套切换；先受控数据，再扩大流量。
7. 回退恢复旧应用版本、旧配置及原资源。新旧环境独立保留，不删除源库、旧桶或旧集合。

迁移/重建工具位于 `backend/scripts/`，由对应实现任务交付；执行前读取最终工具 `--help`，确认 dry-run、目标和显式 apply 参数，不在工具尚未完成时编造命令。真实迁移和生产切换另行执行。

清理工具同样必须要求明确 MySQL 数据库 / Milvus 集合与执行确认，优先只读预览。**安装、启动、打包及自动验收都不能触发清理。** 本文不提供无目标的全量删除命令。

## 构建与打包

前后端迁移完成后、停止并行修改，在专用发布工作区执行：

```bash
# 不联网、不构建的候选清单；只检查路径与文件元数据
bash deploy/pack.sh --list

# 实际发布：Python 3.11 + Node 22.12+，强制安装前端依赖并新构建
PYTHON_BIN=python3.11 bash deploy/pack.sh release
```

真实打包总是先清除旧 `frontend/dist`，执行 `npm ci` 和 `npm run build`，失败不产出发布包；无 `--skip-build`。输出 `multimodal-platform-YYYYMMDD-release.tar.gz`，同名包拒绝覆盖。默认 npm 标准源，可注入 `NPM_REGISTRY`。前端未完成前仅运行 `--list`，不能把已有 dist 当作新构建结果。

清单由 `deploy/release_manifest.py` 维护：根 README/部署说明、后端 Python 应用与脚本、requirements、唯一 `backend/.env.example`、前端构建配置/源码/新静态产物、deploy 与 docs。只递归审查过的目录和文件类型，不递归打包整个工作区。

明确排除所有真实 `.env*`（唯一例外是上述模板）、密钥/证书、迁移导出 JSON/JSONL/CSV/SQL、数据目录、日志、数据库文件、压缩备份、`.tools/` 等本地工具链、虚拟环境、`node_modules`、`.trae/` 和其他隐藏目录。符号链接和硬链接也排除，不跟随链接读取秘密文件。schema 的 Python 迁移代码可以入包，但业务数据不能。

静态白名单不是源码秘密扫描：密钥不能硬编码进允许的 `.py`、`.ts` 或文档。禁止把云凭证放入 `VITE_*`；Vite 会把这些值编译进公开资源。新增运行时文件类型（例如前端源 JSON 或数据驱动配置）须审查后扩充白名单，不能无条件放开目录。

实际包验收需在新构建完成后检查 `tar -tzf` 清单并在隔离目录解压验证文件完整性、字体与前后端合同；本轮不执行实际构建/打包。

## 原地升级（代码与前端产物）

`deploy/update.sh` 用于把 `pack.sh release` 产出的发布包原地覆盖到**已安装并运行过**的部署目录，仅适用于不涉及 schema 迁移、不改动基础设施的版本更新（如前端改版、后端代码修复）。涉及数据库迁移时按上方“本次标注增量升级”执行，不得只跑本脚本。

```bash
# 1. 把发布包复制到服务器（在本地执行）
scp multimodal-platform-YYYYMMDD-release.tar.gz root@<ECS>:/root/

# 2. 在服务器的部署目录执行；首次使用时先从发布包中取出脚本本身
cd /path/to/multimodal-platform
tar -xzf /root/multimodal-platform-YYYYMMDD-release.tar.gz --strip-components=1 \
    multimodal-platform/deploy/update.sh
PORT=3000 APP_ENV_FILE="$(pwd)/backend/.env" \
    bash deploy/update.sh /root/multimodal-platform-YYYYMMDD-release.tar.gz
```

脚本顺序：校验发布包（单一顶层目录、含 `frontend/dist/index.html` 与 `backend/requirements.txt`、不含 `backend/.env`）→ `stop.sh` 停止应用（容器继续运行）→ 把当前 `backend/ frontend/ deploy/ docs/ README.md` 打成 `releases/rollback-<时间戳>.tar.gz` → 删除旧 `frontend/dist` 并解压新包覆盖 → 用现有 `backend/venv` 同步 `requirements.txt` → `start.sh --daemon` 并做 HTTP 探活。

边界：不读取、不生成、不覆盖 `backend/.env`；不触碰 `backend/data`、`logs`、命名卷、标注存储；不重建前端（发布包已含构建结果）；`PORT` 不传则沿用 `start.sh` 默认 3000。回退：`bash deploy/stop.sh`，解压对应 `releases/rollback-*.tar.gz` 到项目根目录，再 `start.sh --daemon`。回退包不含 venv、`node_modules`、数据和配置。

## 故障定位

| 现象 | 检查方向 |
|---|---|
| 配置全为空 | 是否显式设置绝对 `APP_ENV_FILE` 或导出环境变量；不要打印真实配置值 |
| Node / Python 检查失败 | Node 22.12+、Python 3.11 及现有 venv 版本 |
| MySQL / Milvus 超时 | `docker compose ps`、容器日志、回环端口占用、磁盘空间和 `.env` 密码一致性 |
| 方舟 401/403/模型不可用 | 凭证与精确版本授权；不得自动替换 Seed 版本 |
| TOS 预览或视频失败 | 签名有效期、bucket 匹配、特殊字符编码、浏览器/方舟网络、CORS、Range |
| 集合不兼容 | 模型/维度/入库指令版本；另建集合重建，不自动 drop |
| 依赖未就绪 | 保留脱敏服务名、错误类别、请求 ID；禁止写成“接入成功” |
| 任务重启中断 | 检查失败状态，按稳定媒体 ID 幂等重试，不覆盖人工标签 |

## 尚需完成

当前执行环境没有 Docker，Compose 真实拉起和目标 ECS 资源容量尚未验证；TOS、方舟、页面联调、精确模型实测和生产迁移也需后续验收。离线 mock、Compose 静态检查或 Shell 语法通过不等于目标服务器可运行。

本次 T8 部署准备只执行本地定向静态检查，不运行安装/启动/迁移/清理。目标环境 FFmpeg 解码能力、挂载持久性、运行时资源上限及真实升级重启后数据保留均未验证；T3 配置消费还需最终复核。
