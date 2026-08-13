<template>
  <div class="social-publish-page rb-enter">
    <div class="page-header">
      <div>
        <h2>社媒矩阵中心</h2>
        <span class="page-sub">账号授权 · 内容发布 · 数据同步 · 失败重试</span>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
        <el-button @click="focusAccountLogin">新增授权</el-button>
        <el-button type="primary" @click="openCreate" :disabled="loadingAccounts">发起到社媒</el-button>
      </div>
    </div>

    <div class="page-guide">
      社媒矩阵已合并账号授权与发布任务：授权时会直接打开真实平台窗口，登录成功后窗口自动隐藏；随后可选择/上传素材并创建发布任务。
      账号卡片可直接查看该账号发布内容与数据指标，任务失败后可在下方列表编辑并重新发布。
    </div>

    <LoginSessionStatus
      :visible="loginStatusVisible"
      :loading="qrLoading"
      :cancelling="qrCancelling"
      :status="qrPollData.status"
      :message="qrError || qrPollData.message"
      :platform-label="platformLabel(qrPlatform)"
      @cancel="cancelQrLogin"
      @retry="startLogin"
      @dismiss="dismissLoginStatus"
    />

    <section class="matrix-board">
      <div class="panel-card account-auth-panel">
        <div class="section-head">
          <div>
            <h3>账号授权管理</h3>
            <p>管理各平台浏览器会话、实时状态和账号下发布内容。登录和安全验证都在真实平台网页中完成。</p>
          </div>
          <div class="auth-actions">
            <el-select v-model="accountFilterPlatform" placeholder="筛选平台" clearable style="width:140px">
              <el-option v-for="p in socialPlatforms" :key="p.platform" :label="p.name" :value="p.platform" />
            </el-select>
            <el-select v-model="qrPlatform" placeholder="选择登录平台" style="width:180px">
              <el-option
                v-for="p in socialPlatforms"
                :key="p.platform"
                :label="p.name"
                :value="p.platform"
                :disabled="!(p.publish && p.publish.available)"
              />
            </el-select>
            <el-button type="primary" :loading="qrLoading" :disabled="!qrPlatform || qrLoading" @click="startLogin">新增授权</el-button>
          </div>
        </div>

        <div class="account-card-grid" v-loading="loadingAccounts">
          <article
            v-for="acc in visibleSocialAccounts"
            :key="acc.id"
            class="matrix-account-card"
            :class="`is-${acc.cookie_status || 'unknown'}`"
          >
            <div class="account-card-top">
              <div class="account-identity">
                <el-avatar :size="46" :src="acc.avatar_url" class="platform-avatar">{{ accountInitial(acc) }}</el-avatar>
                <div class="identity-text">
                  <div class="identity-name" :title="accountDisplayName(acc)">{{ accountDisplayName(acc) }}</div>
                  <div class="identity-sub">
                    <span>{{ platformLabel(acc.platform) }}</span>
                    <span v-if="accountUsername(acc)">· {{ accountUsername(acc) }}</span>
                  </div>
                </div>
              </div>
              <el-tag size="small" :type="cookieTagType(acc.cookie_status)" effect="light">{{ cookieStatusLabel(acc.cookie_status) }}</el-tag>
            </div>

            <div class="account-metrics">
              <div>
                <b>{{ accountTaskStats(acc).total }}</b>
                <span>发布任务</span>
              </div>
              <div>
                <b class="success">{{ accountTaskStats(acc).published }}</b>
                <span>已发布</span>
              </div>
              <div>
                <b class="danger">{{ accountTaskStats(acc).failed }}</b>
                <span>异常</span>
              </div>
            </div>

            <div class="account-meta">
              <div><span>UID</span><em :title="acc.platform_uid || '—'">{{ acc.platform_uid || '—' }}</em></div>
              <div><span>IP</span><em>{{ acc.current_ip || acc.login_ip || '—' }}</em></div>
              <div><span>最近校验</span><em>{{ formatTime(acc.last_validated_at) }}</em></div>
            </div>

            <div class="account-actions">
              <el-button type="primary" size="small" @click="openAccountContent(acc)">查看内容</el-button>
              <el-button size="small" @click="validateCookie(acc, false)">校验</el-button>
              <el-dropdown trigger="click" @command="(cmd) => handleAccountCmd(cmd, acc)">
                <el-button size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="async_validate">异步校验</el-dropdown-item>
                    <el-dropdown-item command="sync_posts">同步数据</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除账号</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </article>

          <el-empty
            v-if="!loadingAccounts && visibleSocialAccounts.length === 0"
            class="account-empty"
            description="暂无社媒账号，请先登录平台账号"
            :image-size="72"
          >
            <el-button type="primary" :disabled="!qrPlatform" @click="startLogin">打开登录网页</el-button>
          </el-empty>
        </div>
      </div>

      <aside class="matrix-side">
        <div class="panel-card sync-monitor">
          <div class="side-title">同步监控</div>
          <div class="monitor-row">
            <span>有效账号</span>
            <strong>{{ validAccountsCount }} 个</strong>
          </div>
          <div class="monitor-row">
            <span>异常账号</span>
            <strong class="danger">{{ invalidAccountsCount }} 个</strong>
          </div>
          <div class="monitor-row">
            <span>运行中任务</span>
            <strong>{{ runningTasksCount }} 个</strong>
          </div>
          <div class="monitor-row">
            <span>失败待处理</span>
            <strong class="danger">{{ failedTasksCount }} 个</strong>
          </div>
        </div>

        <div class="panel-card sync-flow">
          <div class="side-title">数据同步流程</div>
          <div class="flow-steps">
            <span>授权</span><i></i><span>发布</span><i></i><span>采集</span><i></i><span>回流</span>
          </div>
          <el-button type="primary" plain :disabled="validAccountsCount === 0" @click="refreshAll">手动刷新</el-button>
        </div>
      </aside>
    </section>

    <el-tabs v-model="activeTab" class="mt-12">
      <el-tab-pane label="发布批次" name="batches">
        <div class="panel-card">
          <el-table :data="batches" v-loading="loadingBatches">
            <el-table-column prop="title_snapshot" label="内容标题" min-width="220" show-overflow-tooltip />
            <el-table-column label="模式" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.publish_mode === 'schedule' ? 'warning' : 'primary'">
                  {{ row.publish_mode === 'schedule' ? '定时' : '直接' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="190">
              <template #default="{ row }">
                <div class="progress-cell">
                  <el-progress :percentage="row.total ? Math.round(row.success_count / row.total * 100) : 0" :status="batchStatus(row.status)" />
                  <span class="progress-text"><b class="prog-ok">{{ row.success_count }}</b>/<b class="prog-fail">{{ row.failed_count }}</b>/{{ row.total }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag size="small" :type="batchTagType(row.status)">{{ batchStatusLabel(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }"><el-button link size="small" type="primary" @click="viewBatch(row)">详情</el-button></template>
            </el-table-column>
            <template #empty><el-empty description="暂无发布批次" :image-size="60" /></template>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="任务列表" name="tasks">
        <div class="panel-card">
          <div class="filter-bar">
            <el-select v-model="taskFilter.platform" placeholder="平台" clearable style="width:140px" @change="loadTasks">
              <el-option v-for="(name, code) in PLATFORM_MAP" :key="code" :label="name" :value="code" />
            </el-select>
            <el-select v-model="taskFilter.status" placeholder="状态" clearable style="width:150px" @change="loadTasks">
              <el-option v-for="(meta, code) in TASK_STATUS_MAP" :key="code" :label="meta.label" :value="code" />
            </el-select>
          </div>
          <el-table :data="tasks" v-loading="loadingTasks">
            <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
            <el-table-column label="平台" width="90"><template #default="{ row }">{{ platformLabel(row.platform) }}</template></el-table-column>
            <el-table-column label="素材" width="85"><template #default="{ row }"><el-tag size="small" effect="plain">{{ (row.media_paths || []).length }} 个</el-tag></template></el-table-column>
            <el-table-column label="可见性" width="90"><template #default="{ row }">{{ visibilityLabel(row.publish_params?.visibility) }}</template></el-table-column>
            <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag size="small" :type="taskTagType(row.status)">{{ taskStatusLabel(row.status) }}</el-tag></template></el-table-column>
            <el-table-column label="定时时间" width="170"><template #default="{ row }">{{ row.scheduled_at ? formatTime(row.scheduled_at) : '—' }}</template></el-table-column>
            <el-table-column prop="external_post_id" label="平台ID" width="140" show-overflow-tooltip><template #default="{ row }">{{ row.external_post_id || '—' }}</template></el-table-column>
            <el-table-column label="发布链接" width="110">
              <template #default="{ row }">
                <el-link v-if="row.publish_url" type="primary" :href="row.publish_url" target="_blank" rel="noopener noreferrer">打开</el-link>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="错误信息" min-width="220">
              <template #default="{ row }">
                <el-tooltip v-if="row.error_message" :content="translateError(row.error_message)" placement="top" :show-after="200">
                  <el-tag size="small" type="danger" class="error-tag">{{ translateError(row.error_message) }}</el-tag>
                </el-tooltip>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="retry_count" label="重试" width="60" />
            <el-table-column label="更新时间" width="170"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
            <el-table-column label="操作" width="330">
              <template #default="{ row }">
                <div class="task-actions">
                  <el-button v-if="row.publish_url" link size="small" type="primary" @click="openPostUrl(row)">打开</el-button>
                  <el-button v-if="canMakePrivate(row)" link size="small" type="warning" @click="makePostPrivate(row)">改私密</el-button>
                  <el-button v-if="canRemoteOperate(row)" link size="small" type="danger" @click="deleteRemotePost(row)">删除内容</el-button>
                  <el-button v-if="canEdit(row.status)" link size="small" type="primary" @click="openTaskEdit(row)">编辑</el-button>
                  <el-button v-if="row.status === 'publish_unknown'" link size="small" type="success" @click="confirmUnknownTask(row, 'published')">确认已发布</el-button>
                  <el-button v-if="row.status === 'publish_unknown'" link size="small" type="info" @click="confirmUnknownTask(row, 'not_published')">确认未发布</el-button>
                  <el-button v-if="canRetry(row.status)" link size="small" type="warning" @click="retryTask(row)">重发</el-button>
                  <el-button v-if="canCancel(row.status)" link size="small" type="danger" @click="cancelTask(row)">取消</el-button>
                </div>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无发布任务" :image-size="60" /></template>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="accountContentVisible"
      :title="`${currentAccountName} 的发布内容`"
      width="1080px"
      class="account-content-dialog"
      append-to-body
    >
      <div class="content-dialog-head" v-if="currentAccount">
        <div class="content-account">
          <el-avatar :size="42" :src="currentAccount.avatar_url">{{ accountInitial(currentAccount) }}</el-avatar>
          <div>
            <strong>{{ accountDisplayName(currentAccount) }}</strong>
            <span>{{ platformLabel(currentAccount.platform) }} · {{ currentAccount.platform_uid || '无 UID' }}</span>
          </div>
        </div>
        <div class="content-head-actions">
          <el-button :loading="postsLoading" @click="loadAccountPosts">刷新内容</el-button>
          <el-button type="primary" plain @click="syncAccountPosts(currentAccount)">同步该账号数据</el-button>
        </div>
      </div>

      <el-table :data="accountPosts" v-loading="postsLoading" class="account-post-table">
        <el-table-column prop="title" label="标题" min-width="210" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag size="small" :type="taskTagType(row.status)">{{ taskStatusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="素材" width="70"><template #default="{ row }">{{ row.media_count || 0 }} 个</template></el-table-column>
        <el-table-column label="链接" width="90">
          <template #default="{ row }">
            <el-link v-if="row.publish_url" type="primary" :href="row.publish_url" target="_blank" rel="noopener noreferrer">打开</el-link>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="数据指标" min-width="220">
          <template #default="{ row }">
            <div v-if="row.metrics" class="mini-metrics">
              <span v-if="metricValue(row.metrics, ['views', 'plays', 'reads']) !== '—'">播放 {{ metricValue(row.metrics, ['views', 'plays', 'reads']) }}</span>
              <span v-if="metricValue(row.metrics, ['likes']) !== '—'">赞 {{ metricValue(row.metrics, ['likes']) }}</span>
              <span v-if="metricValue(row.metrics, ['comments']) !== '—'">评 {{ metricValue(row.metrics, ['comments']) }}</span>
              <span v-if="metricValue(row.metrics, ['favorites']) !== '—'">藏 {{ metricValue(row.metrics, ['favorites']) }}</span>
            </div>
            <el-tag v-else size="small" type="info">{{ metricStatusLabel(row.metric_sync_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发布时间" width="165">
          <template #default="{ row }">{{ formatTime(row.finished_at || row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="错误信息" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ translateError(row.error_message || row.metric_error) || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" type="primary" @click="viewPostDetail(row)">详情</el-button>
            <el-button v-if="canMakePrivate(row)" link size="small" type="warning" @click="makePostPrivate(row)">改私密</el-button>
            <el-button v-if="canRemoteOperate(row)" link size="small" type="danger" @click="deleteRemotePost(row)">删除</el-button>
            <el-button link size="small" @click="syncMetrics(row)">同步</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="该账号暂无发布内容" :image-size="60" /></template>
      </el-table>
    </el-dialog>

    <el-dialog v-model="postDetailVisible" title="发布内容详情" width="760px" append-to-body>
      <div v-if="postDetail" v-loading="postDetailLoading">
        <el-descriptions :column="2" border size="small" class="mb-12">
          <el-descriptions-item label="标题">{{ postDetail.title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ platformLabel(postDetail.platform) }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag size="small" :type="taskTagType(postDetail.status)">{{ taskStatusLabel(postDetail.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="发布模式">{{ postDetail.publish_mode === 'schedule' ? '定时' : '直接' }}</el-descriptions-item>
          <el-descriptions-item label="平台ID">{{ postDetail.external_post_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="发布链接">
            <el-link v-if="postDetail.publish_url" :href="postDetail.publish_url" target="_blank" rel="noopener noreferrer" type="primary">查看原文</el-link>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(postDetail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(postDetail.finished_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="postDetail.error_message" label="错误信息" :span="2">
            <span class="danger-text">{{ translateError(postDetail.error_message) }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="postDetail.description" class="detail-block">
          <div class="detail-title">正文</div>
          <div class="detail-text">{{ postDetail.description }}</div>
        </div>
        <div v-if="postDetail.tags && postDetail.tags.length" class="detail-block">
          <div class="detail-title">标签</div>
          <el-tag v-for="t in postDetail.tags" :key="t" size="small" effect="plain" class="tag-chip">{{ t }}</el-tag>
        </div>
        <div v-if="postDetail.metric" class="detail-block">
          <div class="detail-title">数据指标（{{ metricStatusLabel(postDetail.metric.sync_status) }}）</div>
          <div class="metric-cards">
            <div class="metric-card"><strong>{{ metricValue(postDetail.metric.metrics, ['views', 'plays', 'reads']) }}</strong><span>播放/阅读</span></div>
            <div class="metric-card"><strong>{{ metricValue(postDetail.metric.metrics, ['likes']) }}</strong><span>点赞</span></div>
            <div class="metric-card"><strong>{{ metricValue(postDetail.metric.metrics, ['comments']) }}</strong><span>评论</span></div>
            <div class="metric-card"><strong>{{ metricValue(postDetail.metric.metrics, ['favorites']) }}</strong><span>收藏</span></div>
            <div class="metric-card"><strong>{{ metricValue(postDetail.metric.metrics, ['shares']) }}</strong><span>分享</span></div>
          </div>
          <div v-if="postDetail.metric.error_message" class="danger-text metric-error">{{ translateError(postDetail.metric.error_message) }}</div>
        </div>
        <div v-if="postDetail.logs && postDetail.logs.length" class="detail-block">
          <div class="detail-title">发布日志</div>
          <div class="log-list">
            <div v-for="(log, i) in postDetail.logs" :key="i" class="log-item" :class="`log-${log.level}`">
              <span>{{ formatTime(log.created_at) }}</span>
              <b>[{{ log.level }}]</b>
              <em>{{ log.message }}</em>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="postDetail?.publish_url" @click="openPostUrl(postDetail)">打开原文</el-button>
        <el-button v-if="postDetail && canMakePrivate(postDetail)" type="warning" @click="makePostPrivate(postDetail)">改为仅自己可见</el-button>
        <el-button v-if="postDetail && canRemoteOperate(postDetail)" type="danger" @click="deleteRemotePost(postDetail)">删除平台内容</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreate" title="发起到社媒" width="860px" append-to-body>
      <el-form :model="createForm" label-width="108px" class="publish-form">
        <el-form-item label="选择内容">
          <el-select v-model="createForm.content_id" filterable placeholder="搜索内容标题" style="width:100%" @change="onContentChange">
            <el-option v-for="c in contents" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="createForm.title" maxlength="80" show-word-limit placeholder="发布标题，可覆盖内容标题" />
        </el-form-item>
        <el-form-item label="正文">
          <el-input v-model="createForm.description" type="textarea" :rows="5" maxlength="2000" show-word-limit placeholder="发布正文/作品描述" />
        </el-form-item>
        <el-form-item label="话题/标签">
          <el-input v-model="createForm.tagsText" placeholder="用逗号、空格或换行分隔，如 门窗, 封阳台, 广州" />
        </el-form-item>
        <el-form-item label="发布素材">
          <div class="media-picker">
            <el-select v-model="createForm.selected_asset_urls" multiple filterable clearable placeholder="选择素材库图片/视频；视频平台请选择 mp4/mov" style="flex:1">
              <el-option v-for="asset in assets" :key="asset.id" :label="assetOptionLabel(asset)" :value="asset.file_url">
                <span>{{ asset.title }}</span>
                <el-tag size="small" effect="plain" style="margin-left:8px">{{ asset.asset_type }}</el-tag>
              </el-option>
            </el-select>
            <el-upload :show-file-list="false" :http-request="(opt) => uploadAsset(opt, 'create')">
              <el-button :loading="uploading">上传素材</el-button>
            </el-upload>
          </div>
          <div class="publish-tip">已选 {{ effectiveMediaUrls.length }} 个。小红书可用图片/视频；抖音、快手、B站、视频号必须选视频。</div>
        </el-form-item>
        <el-form-item label="封面">
          <el-select v-model="createForm.cover_path" clearable filterable placeholder="可选：选择封面图" style="width:100%">
            <el-option v-for="asset in imageAssets" :key="asset.id" :label="asset.title" :value="asset.file_url" />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="发布模式">
              <el-radio-group v-model="createForm.publish_mode">
                <el-radio value="direct">直接发布</el-radio>
                <el-radio value="schedule">定时发布</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item v-if="createForm.publish_mode === 'schedule'" label="定时时间">
              <el-date-picker v-model="createForm.scheduled_at" type="datetime" placeholder="选择发布时间" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="发布参数">
          <div class="params-grid">
            <el-select v-model="createForm.publish_params.visibility" placeholder="可见性">
              <el-option label="公开" value="public" />
              <el-option label="好友可见" value="friends" />
              <el-option label="仅自己可见" value="private" />
            </el-select>
            <el-input v-model="createForm.publish_params.location" placeholder="定位/POI，如 广州天河" />
            <el-input v-model="createForm.publish_params.topicsText" placeholder="平台话题，逗号分隔" />
            <el-input v-model="createForm.publish_params.theme" placeholder="主题/活动/栏目（可选）" />
            <el-checkbox v-model="createForm.publish_params.allow_comment">允许评论</el-checkbox>
            <el-checkbox v-model="createForm.publish_params.allow_download">允许下载/保存</el-checkbox>
            <el-checkbox v-model="createForm.publish_params.allow_duet">允许合拍/同框</el-checkbox>
          </div>
        </el-form-item>
        <el-form-item label="选择账号">
          <el-select v-model="createForm.selected_account_ids" multiple filterable placeholder="选择已登录的社媒账号" style="width:100%">
            <el-option v-for="acc in socialAccounts" :key="acc.id" :label="`${platformLabel(acc.platform)} - ${acc.nickname || acc.platform_uid || acc.id}`" :value="acc.id" :disabled="acc.cookie_status !== 'valid'">
              <span>{{ platformLabel(acc.platform) }} - {{ acc.nickname || acc.platform_uid || acc.id }}</span>
              <el-tag v-if="acc.cookie_status !== 'valid'" size="small" type="danger" style="margin-left:8px">Cookie 失效</el-tag>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="重复保护">
          <el-checkbox v-model="createForm.allow_duplicate">
            我确认需要在同一账号重复投放完全相同的内容
          </el-checkbox>
          <div class="publish-tip">默认阻止 24 小时内的相同文案、素材和发布参数，防止重复作品。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建发布批次</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="taskEditVisible" title="编辑发布任务" width="900px" append-to-body>
      <el-form :model="taskEditForm" label-width="108px" class="publish-form">
        <el-alert type="info" :closable="false" show-icon class="mb-12" title="编辑保存后不会自动发布；如需立即按新参数执行，请点底部“保存并重新发布”。" />
        <el-row :gutter="12">
          <el-col :span="8"><el-form-item label="平台"><el-input :model-value="platformLabel(taskEditForm.platform)" disabled /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="状态"><el-input :model-value="taskStatusLabel(taskEditForm.status)" disabled /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="可见性"><el-select v-model="taskEditForm.publish_params.visibility"><el-option label="公开" value="public" /><el-option label="好友可见" value="friends" /><el-option label="仅自己可见" value="private" /></el-select></el-form-item></el-col>
        </el-row>
        <el-form-item label="标题"><el-input v-model="taskEditForm.title" maxlength="100" show-word-limit /></el-form-item>
        <el-form-item label="正文"><el-input v-model="taskEditForm.description" type="textarea" :rows="5" maxlength="3000" show-word-limit /></el-form-item>
        <el-form-item label="话题/标签"><el-input v-model="taskEditForm.tagsText" placeholder="逗号、空格或换行分隔" /></el-form-item>
        <el-form-item label="素材">
          <div class="media-picker">
            <el-select v-model="taskEditForm.media_paths" multiple filterable clearable placeholder="选择/修改发布素材" style="flex:1">
              <el-option v-for="asset in assets" :key="asset.id" :label="assetOptionLabel(asset)" :value="asset.file_url" />
            </el-select>
            <el-upload :show-file-list="false" :http-request="(opt) => uploadAsset(opt, 'edit')">
              <el-button :loading="uploading">上传素材</el-button>
            </el-upload>
          </div>
          <div class="publish-tip">当前 {{ (taskEditForm.media_paths || []).length }} 个素材。视频平台必须至少一个 mp4/mov。</div>
        </el-form-item>
        <el-form-item label="封面"><el-select v-model="taskEditForm.cover_path" clearable filterable placeholder="选择封面图" style="width:100%"><el-option v-for="asset in imageAssets" :key="asset.id" :label="asset.title" :value="asset.file_url" /></el-select></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="发布模式"><el-radio-group v-model="taskEditForm.publish_mode"><el-radio value="direct">直接发布</el-radio><el-radio value="schedule">定时发布</el-radio></el-radio-group></el-form-item></el-col>
          <el-col :span="12"><el-form-item v-if="taskEditForm.publish_mode === 'schedule'" label="定时时间"><el-date-picker v-model="taskEditForm.scheduled_at" type="datetime" style="width:100%" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="发布参数">
          <div class="params-grid">
            <el-input v-model="taskEditForm.publish_params.location" placeholder="定位/POI" />
            <el-input v-model="taskEditForm.publish_params.topicsText" placeholder="平台话题，逗号分隔" />
            <el-input v-model="taskEditForm.publish_params.theme" placeholder="主题/活动/栏目" />
            <el-checkbox v-model="taskEditForm.publish_params.allow_comment">允许评论</el-checkbox>
            <el-checkbox v-model="taskEditForm.publish_params.allow_download">允许下载/保存</el-checkbox>
            <el-checkbox v-model="taskEditForm.publish_params.allow_duet">允许合拍/同框</el-checkbox>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="taskEditVisible = false">取消</el-button>
        <el-button :loading="savingTask" @click="saveTaskEdit(false)">保存</el-button>
        <el-button type="primary" :loading="savingTask" @click="saveTaskEdit(true)">保存并重新发布</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchDetailVisible" title="批次详情" width="840px" append-to-body>
      <div v-if="batchDetail">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="内容标题">{{ batchDetail.title_snapshot }}</el-descriptions-item>
          <el-descriptions-item label="模式">{{ batchDetail.publish_mode === 'schedule' ? '定时' : '直接' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ batchStatusLabel(batchDetail.status) }}</el-descriptions-item>
          <el-descriptions-item label="总数">{{ batchDetail.total }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ batchDetail.success_count }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ batchDetail.failed_count }}</el-descriptions-item>
        </el-descriptions>
        <h4 style="margin:16px 0 8px">任务列表</h4>
        <el-table :data="batchDetail.tasks || []" size="small">
          <el-table-column prop="platform" label="平台" width="100"><template #default="{ row }">{{ platformLabel(row.platform) }}</template></el-table-column>
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag size="small" :type="taskTagType(row.status)">{{ taskStatusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="错误" min-width="220" show-overflow-tooltip><template #default="{ row }">{{ translateError(row.error_message) || '—' }}</template></el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Refresh } from '@element-plus/icons-vue'
import request from '../../utils/request'
import { errorMessageFrom, humanizeError } from '../../utils/errorMessage'
import LoginSessionStatus from '../../components/LoginSessionStatus.vue'

const route = useRoute()
const router = useRouter()
const activeTab = ref('batches')
const loadingBatches = ref(false)
const loadingTasks = ref(false)
const loadingAccounts = ref(false)
const creating = ref(false)
const uploading = ref(false)
const savingTask = ref(false)
const showCreate = ref(false)
const batchDetailVisible = ref(false)
const taskEditVisible = ref(false)
const accountFilterPlatform = ref('')
const socialPlatforms = ref([])
const qrPlatform = ref('')
const qrLoading = ref(false)
const qrCancelling = ref(false)
const qrError = ref('')
const qrSessionId = ref('')
const qrPollData = ref({ status: '', message: '' })
const loginStatusVisible = computed(() => (
  qrLoading.value
  || !!qrSessionId.value
  || ['starting', 'waiting', 'scanned', 'failed', 'expired'].includes(qrPollData.value.status)
))
let qrPollTimer = null
let qrLoginAttempt = 0
const accountContentVisible = ref(false)
const postsLoading = ref(false)
const accountPosts = ref([])
const currentAccount = ref(null)
const currentAccountId = ref('')
const postDetailVisible = ref(false)
const postDetailLoading = ref(false)
const postDetail = ref(null)

const batches = ref([])
const tasks = ref([])
const allTasks = ref([])
const socialAccounts = ref([])
const contents = ref([])
const assets = ref([])
const batchDetail = ref(null)

const taskFilter = reactive({ platform: '', status: '' })

const defaultParams = () => ({
  visibility: 'public',
  location: '',
  topicsText: '',
  theme: '',
  allow_comment: true,
  allow_download: true,
  allow_duet: false,
})

const createForm = reactive({
  content_id: '', title: '', description: '', tagsText: '',
  publish_mode: 'direct', scheduled_at: null,
  selected_account_ids: [], selected_asset_urls: [], cover_path: '',
  request_key: '', allow_duplicate: false,
  publish_params: defaultParams(),
})

const taskEditForm = reactive({
  id: '', platform: '', status: '', title: '', description: '', tagsText: '',
  media_paths: [], cover_path: '', publish_mode: 'direct', scheduled_at: null,
  publish_params: defaultParams(),
})

const selectedContent = computed(() => contents.value.find((c) => c.id === createForm.content_id))
const selectedContentMediaUrls = computed(() => selectedContent.value?.media_urls || [])
const effectiveMediaUrls = computed(() => Array.from(new Set([...(selectedContentMediaUrls.value || []), ...(createForm.selected_asset_urls || [])].filter(Boolean))))
const selectedTargetPlatforms = computed(() => createForm.selected_account_ids.map((id) => socialAccounts.value.find((a) => a.id === id)?.platform).filter(Boolean))
const imageAssets = computed(() => assets.value.filter((a) => a.asset_type === 'image' || /\.(jpg|jpeg|png|webp|gif)(\?|$)/i.test(a.file_url || '')))
const visibleSocialAccounts = computed(() => {
  if (!accountFilterPlatform.value) return socialAccounts.value
  return socialAccounts.value.filter((a) => a.platform === accountFilterPlatform.value)
})
const validAccountsCount = computed(() => socialAccounts.value.filter((a) => a.cookie_status === 'valid').length)
const invalidAccountsCount = computed(() => socialAccounts.value.filter((a) => a.cookie_status && a.cookie_status !== 'valid').length)
const runningTasksCount = computed(() => allTasks.value.filter((t) => ['queued', 'running', 'scheduled'].includes(t.status)).length)
const failureStatuses = new Set(['failed', 'publish_error', 'media_required', 'cookie_missing', 'cookie_invalid', 'dispatch_failed', 'account_restricted', 'not_published'])
const failedTasksCount = computed(() => allTasks.value.filter((t) => failureStatuses.has(t.status)).length)
const currentAccountName = computed(() => currentAccount.value ? accountDisplayName(currentAccount.value) : '账号')
const videoOnlyPlatforms = new Set(['douyin', 'kuaishou', 'bilibili', 'channels'])
const mediaRequiredPlatforms = new Set(['xiaohongshu', 'douyin', 'kuaishou', 'bilibili', 'channels'])
const isVideoUrl = (url) => /\.(mp4|mov|m4v|avi|mkv|webm)(\?|$)/i.test(String(url || ''))

const hasActiveTasks = computed(() => allTasks.value.some((t) => ['queued', 'running', 'scheduled'].includes(t.status)) || batches.value.some((b) => ['pending', 'running', 'scheduled'].includes(b.status)))
let publishPollTimer = null
function startPublishPolling() { if (!publishPollTimer) publishPollTimer = setInterval(refreshAll, 5000) }
function stopPublishPolling() { if (publishPollTimer) { clearInterval(publishPollTimer); publishPollTimer = null } }
watch(hasActiveTasks, (val) => (val ? startPublishPolling() : stopPublishPolling()))

const PLATFORM_MAP = { xiaohongshu: '小红书', channels: '视频号', douyin: '抖音', kuaishou: '快手', bilibili: 'B站' }
const platformLabel = (p) => PLATFORM_MAP[p] || p
const VISIBILITY_MAP = { public: '公开', friends: '好友', private: '私密' }
const visibilityLabel = (v) => VISIBILITY_MAP[v] || '公开'
const BATCH_STATUS_MAP = { pending: { label: '待执行', type: 'info' }, scheduled: { label: '定时待发', type: 'warning' }, running: { label: '执行中', type: 'primary' }, completed: { label: '已完成', type: 'success' }, partial_failed: { label: '部分失败', type: 'warning' }, failed: { label: '失败', type: 'danger' } }
const TASK_STATUS_MAP = { pending: { label: '待执行', type: 'info' }, scheduled: { label: '定时待发', type: 'warning' }, queued: { label: '排队中', type: 'info' }, running: { label: '执行中', type: 'primary' }, published: { label: '已发布', type: 'success' }, reviewing: { label: '审核中', type: 'primary' }, deleted: { label: '已删除', type: 'info' }, failed: { label: '失败', type: 'danger' }, cancelled: { label: '已取消', type: 'info' }, publish_unknown: { label: '发布结果待确认', type: 'warning' }, not_published: { label: '已确认未发布', type: 'info' }, media_required: { label: '缺少素材', type: 'warning' }, publish_error: { label: '发布异常', type: 'danger' }, cookie_missing: { label: '账号登录失效', type: 'danger' }, cookie_invalid: { label: '账号登录失效', type: 'danger' }, dispatch_failed: { label: '队列派发失败', type: 'danger' }, account_restricted: { label: '账号受限', type: 'danger' }, needs_phone_captcha: { label: '需验证码', type: 'warning' }, needs_human_captcha: { label: '需人机验证', type: 'warning' }, awaiting_resume: { label: '等待继续', type: 'info' } }
const batchStatusLabel = (s) => BATCH_STATUS_MAP[s]?.label || s
const batchTagType = (s) => BATCH_STATUS_MAP[s]?.type || 'info'
const batchStatus = (s) => (s === 'completed' ? 'success' : s === 'failed' ? 'exception' : s === 'partial_failed' ? 'warning' : undefined)
const taskStatusLabel = (s) => TASK_STATUS_MAP[s]?.label || s
const taskTagType = (s) => TASK_STATUS_MAP[s]?.type || 'info'
const canRetry = (s) => ['failed', 'cancelled', 'media_required', 'publish_error', 'cookie_missing', 'cookie_invalid', 'dispatch_failed', 'account_restricted', 'pending', 'not_published'].includes(s)
const canCancel = (s) => ['pending', 'queued', 'running', 'scheduled'].includes(s)
const canEdit = (s) => ['pending', 'scheduled', 'queued', 'failed', 'cancelled', 'media_required', 'publish_error', 'cookie_missing', 'cookie_invalid', 'dispatch_failed', 'account_restricted', 'not_published'].includes(s)
const canRemoteOperate = (row) => ['published', 'reviewing'].includes(row?.status)
const canMakePrivate = (row) => canRemoteOperate(row) && row?.platform !== 'bilibili' && row?.publish_params?.visibility !== 'private'
const COOKIE_STATUS_MAP = {
  valid: { label: '已授权', type: 'success' },
  invalid: { label: '已失效', type: 'danger' },
  expired: { label: '已过期', type: 'warning' },
  unknown: { label: '未知', type: 'info' },
}
const cookieStatusLabel = (s) => COOKIE_STATUS_MAP[s]?.label || s || '未知'
const cookieTagType = (s) => COOKIE_STATUS_MAP[s]?.type || 'info'
const metricStatusLabel = (s) => ({ pending: '待同步', synced: '已同步', unavailable: '不可采集', failed: '同步失败' }[s] || s || '未采集')

const formatTime = (t) => {
  if (!t) return '—'
  const d = new Date(t); const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const translateError = (msg) => msg ? humanizeError(msg, { context: 'publish' }) : ''
const splitWords = (text) => Array.from(new Set(String(text || '').split(/[，,\s#]+/).map((x) => x.trim()).filter(Boolean)))
const newPublishRequestKey = () => globalThis.crypto?.randomUUID?.() || `publish-${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
const assetOptionLabel = (asset) => `${asset.title || '未命名素材'} · ${asset.asset_type || 'file'}`
const detectAssetType = (file) => (/video\//.test(file.type) || /\.(mp4|mov|m4v|avi|mkv|webm)$/i.test(file.name) ? 'video' : 'image')
const buildParamsPayload = (params) => ({
  visibility: params.visibility || 'public',
  location: params.location || '',
  topics: splitWords(params.topicsText),
  theme: params.theme || '',
  allow_comment: !!params.allow_comment,
  allow_download: !!params.allow_download,
  allow_duet: !!params.allow_duet,
})
const accountDisplayName = (acc) => acc?.nickname || acc?.user_info?.name || acc?.username || acc?.platform_uid || '未命名账号'
const accountUsername = (acc) => acc?.username || acc?.user_info?.username || acc?.user_info?.extra?.unique_id || acc?.user_info?.extra?.red_id || ''
const accountInitial = (acc) => String(accountDisplayName(acc) || '?').slice(0, 1).toUpperCase()
const accountTaskStats = (acc) => {
  const rows = allTasks.value.filter((t) => t.social_account_id === acc.id || (t.account_ref && t.account_ref === acc.platform_uid))
  return {
    total: rows.length,
    published: rows.filter((t) => ['published', 'reviewing'].includes(t.status)).length,
    failed: rows.filter((t) => failureStatuses.has(t.status)).length,
  }
}
const metricValue = (metrics, keys) => {
  const data = metrics || {}
  for (const key of keys) {
    const value = data[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return '—'
}

async function loadBatches() { loadingBatches.value = true; try { const res = await request.get('/social/publish/batches', { params: { page_size: 50 } }); batches.value = res.data || [] } finally { loadingBatches.value = false } }
async function loadTasks() {
  loadingTasks.value = true
  try {
    const params = { page_size: 50 }
    if (taskFilter.platform) params.platform = taskFilter.platform
    if (taskFilter.status) params.status = taskFilter.status
    const filtered = !!(taskFilter.platform || taskFilter.status)
    const [listRes, allRes] = await Promise.all([
      request.get('/social/publish/tasks', { params }),
      filtered ? request.get('/social/publish/tasks', { params: { page_size: 50 } }) : Promise.resolve(null),
    ])
    tasks.value = listRes.data || []
    allTasks.value = (allRes?.data || listRes.data) || []
  } finally {
    loadingTasks.value = false
  }
}
async function loadSocialAccounts() { loadingAccounts.value = true; try { const res = await request.get('/social/accounts/', { params: { page_size: 100, status: 'active' } }); socialAccounts.value = res.data || [] } finally { loadingAccounts.value = false } }
async function loadSocialPlatforms() {
  try {
    const res = await request.get('/social/accounts/platforms')
    socialPlatforms.value = res.data || []
    if (!qrPlatform.value) qrPlatform.value = socialPlatforms.value.find((p) => p.publish?.available)?.platform || ''
  } catch (e) { /* ignore */ }
}
async function loadContents() { const res = await request.get('/content/', { params: { page_size: 100 } }); contents.value = (res.data || []).filter((c) => ['ai_generated', 'risk_checked', 'approved', 'human_reviewed', 'scheduled', 'published'].includes(c.status)) }
async function loadAssets() { const res = await request.get('/assets/', { params: { page_size: 100 } }); assets.value = res.data || [] }

function focusAccountLogin() {
  if (!qrPlatform.value) qrPlatform.value = socialPlatforms.value.find((p) => p.publish?.available)?.platform || ''
  if (!qrPlatform.value) return ElMessage.warning('暂无可用登录平台')
  startLogin()
}

async function startLogin() {
  if (!qrPlatform.value) return ElMessage.warning('请选择平台')
  const attempt = ++qrLoginAttempt
  stopQrPolling()
  const previousSessionId = qrSessionId.value
  if (previousSessionId) {
    try {
      await request.post('/social/accounts/login/cancel', null, {
        params: { session_id: previousSessionId },
        silentError: true,
      })
    } catch (e) { /* ignore */ }
  }
  qrSessionId.value = ''
  qrError.value = ''
  qrPollData.value = { status: 'starting', message: '' }
  qrLoading.value = true
  try {
    const res = await request.post('/social/accounts/login/start', { platform: qrPlatform.value }, { timeout: 120000, silentError: true })
    const sessionId = res.data?.session_id
    if (attempt !== qrLoginAttempt) {
      if (sessionId) {
        try {
          await request.post('/social/accounts/login/cancel', null, {
            params: { session_id: sessionId },
            silentError: true,
          })
        } catch (e) { /* ignore */ }
      }
      return
    }
    if (!sessionId) throw new Error('登录窗口启动失败：服务端未返回登录会话')
    qrSessionId.value = sessionId
    qrPollData.value = {
      status: res.data?.status || 'waiting',
      message: res.data?.message || '请在弹出的真实平台窗口中完成登录',
    }
    startQrPolling(attempt)
  } catch (e) {
    if (attempt !== qrLoginAttempt) return
    const reason = errorMessageFrom(e, '登录浏览器启动失败，请重试。', 'login')
    qrError.value = reason
    qrPollData.value = { status: 'failed', message: reason }
    qrSessionId.value = ''
    stopQrPolling()
  } finally {
    if (attempt === qrLoginAttempt) qrLoading.value = false
  }
}

function startQrPolling(attempt) {
  stopQrPolling()
  qrPollTimer = setInterval(async () => {
    const sessionId = qrSessionId.value
    if (!sessionId || attempt !== qrLoginAttempt) return
    try {
      const res = await request.get('/social/accounts/login/status', { params: { session_id: sessionId }, silentError: true })
      if (attempt !== qrLoginAttempt || sessionId !== qrSessionId.value) return
      const payload = res.data || {}
      qrPollData.value = { status: payload.status, message: payload.message || '' }
      if (payload.status === 'confirmed') {
        stopQrPolling()
        qrSessionId.value = ''
        qrError.value = ''
        qrPollData.value = { status: '', message: '' }
        await loadSocialAccounts()
      } else if (payload.status === 'expired' || payload.status === 'failed') {
        qrError.value = humanizeError(payload.message, {
          context: 'login',
          fallback: '登录失败或会话已超时，请重新打开登录网页。',
        })
        qrSessionId.value = ''
        stopQrPolling()
      }
    } catch (e) { /* 轮询静默，避免 toast 刷屏 */ }
  }, 2500)
}

function stopQrPolling() {
  if (qrPollTimer) {
    clearInterval(qrPollTimer)
    qrPollTimer = null
  }
}

async function cancelQrLogin() {
  ++qrLoginAttempt
  const sessionId = qrSessionId.value
  stopQrPolling()
  qrLoading.value = false
  qrSessionId.value = ''
  qrError.value = ''
  qrPollData.value = { status: '', message: '' }
  if (!sessionId) return
  qrCancelling.value = true
  try {
    await request.post('/social/accounts/login/cancel', null, {
      params: { session_id: sessionId },
      silentError: true,
    })
  } catch (e) { /* ignore */ }
  finally { qrCancelling.value = false }
}

function dismissLoginStatus() {
  qrError.value = ''
  qrPollData.value = { status: '', message: '' }
}

async function validateCookie(row, asyncMode = false) {
  if (asyncMode) {
    await request.post(`/social/accounts/${row.id}/validate-async`)
    ElMessage.success('Cookie 校验已派发到 worker')
    return
  }
  ElMessage.info('正在校验 Cookie，请稍候...')
  const res = await request.post(`/social/accounts/${row.id}/validate`)
  const payload = res.data || {}
  if (payload.valid) ElMessage.success('Cookie 有效')
  else ElMessage.warning(`Cookie 失效：${payload.reason || '未知原因'}`)
  await loadSocialAccounts()
}

async function confirmAction(message, title, options = {}) {
  try {
    await ElMessageBox.confirm(message, title, options)
    return true
  } catch (reason) {
    if (reason === 'cancel' || reason === 'close') return false
    throw reason
  }
}

async function deleteSocialAccount(row) {
  if (!await confirmAction(`确认删除社媒账号“${accountDisplayName(row)}”？同时会删除本地 Cookie 文件。`, '删除账号', { type: 'warning' })) return
  await request.delete(`/social/accounts/${row.id}`)
  ElMessage.success('账号已删除')
  await loadSocialAccounts()
}

async function syncAccountPosts(row) {
  await request.post(`/social/accounts/${row.id}/sync-posts`)
  ElMessage.success('该账号数据同步任务已派发')
  if (currentAccountId.value === row.id) setTimeout(loadAccountPosts, 1200)
}

function handleAccountCmd(cmd, row) {
  if (cmd === 'async_validate') validateCookie(row, true)
  if (cmd === 'sync_posts') syncAccountPosts(row)
  if (cmd === 'delete') deleteSocialAccount(row)
}

async function openAccountContent(row) {
  currentAccount.value = row
  currentAccountId.value = row.id
  accountContentVisible.value = true
  await loadAccountPosts()
}

async function loadAccountPosts() {
  if (!currentAccountId.value) return
  postsLoading.value = true
  try {
    const res = await request.get(`/social/accounts/${currentAccountId.value}/posts`, { params: { page_size: 80 } })
    accountPosts.value = res.data || []
  } finally {
    postsLoading.value = false
  }
}

async function viewPostDetail(row) {
  postDetailVisible.value = true
  postDetailLoading.value = true
  postDetail.value = null
  try {
    const res = await request.get(`/social/accounts/${currentAccountId.value}/posts/${row.id}`)
    postDetail.value = { ...(res.data || {}), social_account_id: currentAccountId.value }
  } finally {
    postDetailLoading.value = false
  }
}

async function syncMetrics(row) {
  await request.post(`/social/accounts/${currentAccountId.value}/posts/${row.id}/sync-metrics`)
  ElMessage.success('指标同步任务已派发')
  setTimeout(loadAccountPosts, 1500)
}

function postAccountId(row) {
  return row?.social_account_id || currentAccountId.value
}

function openPostUrl(row) {
  const url = row?.publish_url
  if (!url) return ElMessage.warning('暂无发布链接')
  window.open(url, '_blank', 'noopener,noreferrer')
}

async function deleteRemotePost(row) {
  const accountId = postAccountId(row)
  if (!accountId) return ElMessage.warning('缺少账号信息，无法删除平台内容')
  if (!await confirmAction(`确认删除/下架平台内容“${row.title || row.id}”？该操作会打开平台后台自动执行，删除后不可恢复。`, '删除平台内容', { type: 'warning' })) return
  await request.post(`/social/accounts/${accountId}/posts/${row.id}/delete`, null, { timeout: 180000 })
  ElMessage.success('平台内容删除/下架操作已提交')
  if (postDetailVisible.value && postDetail.value?.id === row.id) postDetailVisible.value = false
  await refreshAll()
}

async function makePostPrivate(row) {
  const accountId = postAccountId(row)
  if (!accountId) return ElMessage.warning('缺少账号信息，无法调整可见性')
  if (row.platform === 'bilibili') return ElMessage.warning('B站网页发布/管理页没有稳定的仅自己可见选项')
  if (!await confirmAction(`确认将“${row.title || row.id}”调整为仅自己可见？`, '调整可见性', { type: 'warning' })) return
  await request.post(`/social/accounts/${accountId}/posts/${row.id}/visibility`, { visibility: 'private' }, { timeout: 180000 })
  ElMessage.success('已尝试调整为仅自己可见')
  await refreshAll()
  if (postDetailVisible.value && postDetail.value?.id === row.id) {
    try {
      const res = await request.get(`/social/accounts/${accountId}/posts/${row.id}`)
      postDetail.value = { ...(res.data || {}), social_account_id: accountId }
    } catch (e) { /* ignore */ }
  }
}

async function openCreate() {
  if (socialAccounts.value.filter((a) => a.cookie_status === 'valid').length === 0) return ElMessage.warning('暂无可用社媒账号，请先登录平台账号')
  Object.assign(createForm, { content_id: '', title: '', description: '', tagsText: '', publish_mode: 'direct', scheduled_at: null, selected_account_ids: [], selected_asset_urls: [], cover_path: '', request_key: newPublishRequestKey(), allow_duplicate: false, publish_params: defaultParams() })
  showCreate.value = true
  if (contents.value.length === 0) await loadContents()
  if (assets.value.length === 0) await loadAssets()
}
function onContentChange() {
  const c = selectedContent.value
  if (!c) return
  createForm.title = c.title || ''
  createForm.description = c.body_text || ''
  createForm.tagsText = (c.tags || []).join(', ')
}
function validatePayloadPlatforms(platforms, mediaUrls) {
  if (platforms.some((p) => mediaRequiredPlatforms.has(p)) && mediaUrls.length === 0) { ElMessage.warning('真实发布必须选择或上传图片/视频素材'); return false }
  if (platforms.some((p) => videoOnlyPlatforms.has(p)) && !mediaUrls.some(isVideoUrl)) { ElMessage.warning('抖音、快手、B站、视频号必须选择 mp4/mov 等视频素材'); return false }
  return true
}
async function submitCreate() {
  if (!createForm.content_id) return ElMessage.warning('请选择内容')
  if (createForm.selected_account_ids.length === 0) return ElMessage.warning('请选择至少一个社媒账号')
  if (createForm.publish_mode === 'schedule' && !createForm.scheduled_at) return ElMessage.warning('请选择定时发布时间')
  const targets = createForm.selected_account_ids.map((id) => { const acc = socialAccounts.value.find((a) => a.id === id); return { social_account_id: id, platform: acc?.platform || '' } }).filter((t) => t.platform)
  const mediaUrls = effectiveMediaUrls.value
  if (!validatePayloadPlatforms(targets.map((t) => t.platform), mediaUrls)) return
  creating.value = true
  try {
    if (!createForm.request_key) createForm.request_key = newPublishRequestKey()
    const res = await request.post('/social/publish/', { content_id: createForm.content_id, targets, publish_mode: createForm.publish_mode, scheduled_at: createForm.scheduled_at ? new Date(createForm.scheduled_at).toISOString() : null, media_urls: mediaUrls, cover_path: createForm.cover_path || null, title: createForm.title, description: createForm.description, tags: splitWords(createForm.tagsText), publish_params: buildParamsPayload(createForm.publish_params), request_key: createForm.request_key, allow_duplicate: !!createForm.allow_duplicate })
    ElMessage.success(res.data?.reused ? '重复请求已复用原发布批次，没有再次投递' : `发布批次已创建，共 ${targets.length} 个任务`)
    showCreate.value = false; refreshAll()
  } finally { creating.value = false }
}

async function uploadAsset(opt, target) {
  const file = opt.file
  uploading.value = true
  try {
    const form = new FormData(); form.append('file', file)
    const assetType = detectAssetType(file)
    const res = await request.post('/assets/upload', form, { params: { title: file.name, asset_type: assetType, category: 'social_publish', is_public: false, tags: JSON.stringify(['社媒发布', assetType]) }, headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 })
    const asset = res.data
    assets.value.unshift(asset)
    if (target === 'create') createForm.selected_asset_urls = Array.from(new Set([...(createForm.selected_asset_urls || []), asset.file_url]))
    if (target === 'edit') taskEditForm.media_paths = Array.from(new Set([...(taskEditForm.media_paths || []), asset.file_url]))
    if (String(asset.file_url || '').startsWith('mock://')) ElMessage.warning('素材上传返回 mock 地址，真实平台不能发布，请检查 MinIO')
    else ElMessage.success('素材已上传并选中')
    opt.onSuccess?.(asset)
  } catch (e) { opt.onError?.(e) } finally { uploading.value = false }
}

async function viewBatch(row) { const res = await request.get(`/social/publish/batches/${row.id}`); batchDetail.value = res.data; batchDetailVisible.value = true }
function openTaskEdit(row) {
  taskEditForm.id = row.id; taskEditForm.platform = row.platform; taskEditForm.status = row.status
  taskEditForm.title = row.title || ''; taskEditForm.description = row.description || ''; taskEditForm.tagsText = (row.tags || []).join(', ')
  taskEditForm.media_paths = [...(row.media_paths || [])]; taskEditForm.cover_path = row.cover_path || ''
  taskEditForm.publish_mode = row.publish_mode || 'direct'; taskEditForm.scheduled_at = row.scheduled_at ? new Date(row.scheduled_at) : null
  const p = row.publish_params || {}
  taskEditForm.publish_params = { ...defaultParams(), ...p, topicsText: (p.topics || p.tags || []).join(', ') }
  taskEditVisible.value = true
  if (assets.value.length === 0) loadAssets()
}
async function saveTaskEdit(redispatch = false) {
  if (!taskEditForm.title) return ElMessage.warning('标题不能为空')
  if (!validatePayloadPlatforms([taskEditForm.platform], taskEditForm.media_paths || [])) return
  savingTask.value = true
  try {
    await request.put(`/social/publish/tasks/${taskEditForm.id}`, { title: taskEditForm.title, description: taskEditForm.description, tags: splitWords(taskEditForm.tagsText), media_paths: taskEditForm.media_paths, cover_path: taskEditForm.cover_path || null, publish_mode: taskEditForm.publish_mode, scheduled_at: taskEditForm.scheduled_at ? new Date(taskEditForm.scheduled_at).toISOString() : null, publish_params: buildParamsPayload(taskEditForm.publish_params) })
    if (redispatch) await request.post(`/social/publish/tasks/${taskEditForm.id}/retry`)
    ElMessage.success(redispatch ? '已保存并重新发布' : '已保存任务参数')
    taskEditVisible.value = false; refreshAll()
  } finally { savingTask.value = false }
}
async function retryTask(row) {
  if (!await confirmAction(`确认按当前参数重新发布“${row.title}”？`, '重新发布任务', {
    type: 'info',
    confirmButtonText: '确认重发',
    cancelButtonText: '取消',
  })) return
  await request.post(`/social/publish/tasks/${row.id}/retry`)
  ElMessage.success('任务已重新派发')
  loadTasks()
}
async function confirmUnknownTask(row, outcome) {
  const published = outcome === 'published'
  const message = published
    ? `请确认你已经在${platformLabel(row.platform)}创作后台看到“${row.title}”确实发布成功。确认后系统会记为已发布。`
    : `请确认你已经在${platformLabel(row.platform)}创作后台检查过，“${row.title}”确实没有发布。确认后才允许安全重试。`
  if (!await confirmAction(message, published ? '确认已发布' : '确认未发布', {
    type: published ? 'success' : 'warning',
    confirmButtonText: published ? '确实已发布' : '确实未发布',
    cancelButtonText: '再检查一下',
  })) return
  await request.post(`/social/publish/tasks/${row.id}/confirm`, {
    outcome,
    note: published ? '运营人员已在平台创作后台人工确认发布成功' : '运营人员已在平台创作后台人工确认未发布',
  })
  ElMessage.success(published ? '已记为发布成功' : '已确认未发布，现在可以安全重试')
  await refreshAll()
}
async function cancelTask(row) { if (!await confirmAction(`确认取消任务“${row.title}”？`, '取消发布任务')) return; await request.post(`/social/publish/tasks/${row.id}/cancel`); ElMessage.success('任务已取消'); loadTasks() }
async function refreshAll() {
  const jobs = [loadBatches(), loadTasks(), loadSocialAccounts(), loadSocialPlatforms()]
  if (accountContentVisible.value && currentAccountId.value) jobs.push(loadAccountPosts())
  await Promise.allSettled(jobs)
}

onMounted(async () => {
  await Promise.all([
    loadBatches(),
    loadTasks(),
    loadSocialAccounts(),
    loadSocialPlatforms(),
    loadAssets(),
  ])
  if (route.query.content_id) {
    await loadContents()
    await openCreate()
    createForm.content_id = String(route.query.content_id)
    onContentChange()
  }
})
onUnmounted(() => {
  stopPublishPolling()
  stopQrPolling()
})
</script>

<style scoped>
.social-publish-page { padding: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-header h2 { margin: 0 0 4px; font-size: 24px; font-weight: 800; letter-spacing: -0.02em; }
.page-sub, .muted { color: var(--color-ink-tertiary); font-size: 13px; }
.header-actions, .filter-bar, .media-picker { display: flex; gap: 10px; align-items: center; }
.page-guide { margin-bottom: 12px; padding: 12px 16px; font-size: 13px; color: var(--color-ink-secondary); line-height: 1.6; border-radius: var(--radius-lg); background: rgba(15, 23, 42, .03); }
.mt-12 { margin-top: 12px; } .mb-12 { margin-bottom: 12px; }
.panel-card { border-radius: var(--radius-lg); padding: 4px; }
.matrix-board { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 16px; align-items: start; margin-bottom: 14px; }
.account-auth-panel { padding: 18px; background: #fff; border: 1px solid var(--color-border); }
.section-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 16px; }
.section-head h3 { margin: 0 0 6px; font-size: 18px; line-height: 1.25; color: var(--color-ink); }
.section-head p { margin: 0; font-size: 13px; color: var(--color-ink-tertiary); line-height: 1.5; }
.auth-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.account-card-grid { min-height: 170px; display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 14px; }
.matrix-account-card { padding: 16px; border: 1px solid #e5eaf2; border-radius: 14px; background: linear-gradient(180deg, #fff 0%, #fbfdff 100%); box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04); display: flex; flex-direction: column; gap: 14px; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.matrix-account-card:hover { transform: translateY(-1px); border-color: rgba(15, 107, 197, .28); box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08); }
.matrix-account-card.is-invalid, .matrix-account-card.is-expired { background: linear-gradient(180deg, #fff 0%, #fff7f7 100%); border-color: #fecaca; }
.account-card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.account-identity { display: flex; gap: 11px; align-items: center; min-width: 0; }
.platform-avatar { flex-shrink: 0; background: #e8f2ff; color: var(--wm-primary); font-weight: 700; }
.identity-text { min-width: 0; }
.identity-name { font-size: 15px; font-weight: 700; color: var(--color-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 150px; }
.identity-sub { margin-top: 3px; font-size: 12px; color: var(--color-ink-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 170px; }
.account-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 10px 0; border-top: 1px solid #edf2f7; border-bottom: 1px solid #edf2f7; }
.account-metrics div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.account-metrics b { font-size: 20px; line-height: 1; color: var(--color-ink); }
.account-metrics b.success { color: var(--color-success); }
.account-metrics b.danger { color: var(--color-danger); }
.account-metrics span { font-size: 11px; color: var(--color-ink-tertiary); }
.account-meta { display: grid; gap: 6px; font-size: 12px; }
.account-meta div { display: flex; justify-content: space-between; gap: 12px; min-width: 0; }
.account-meta span { color: var(--color-ink-tertiary); flex-shrink: 0; }
.account-meta em { color: var(--color-ink-secondary); font-style: normal; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.account-actions .el-button { min-width: 72px; }
.account-empty { grid-column: 1 / -1; padding: 20px 0; }
.matrix-side { display: grid; gap: 14px; }
.sync-monitor, .sync-flow { padding: 18px; background: #fff; border: 1px solid var(--color-border); }
.side-title { font-size: 16px; font-weight: 700; color: var(--color-ink); margin-bottom: 14px; }
.monitor-row { display: flex; align-items: baseline; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #edf2f7; }
.monitor-row:last-child { border-bottom: 0; }
.monitor-row span { font-size: 13px; color: var(--color-ink-tertiary); }
.monitor-row strong { font-size: 22px; color: var(--color-ink); }
.monitor-row strong.danger, .danger-text { color: var(--color-danger); }
.flow-steps { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; color: var(--color-ink-secondary); font-size: 12px; }
.flow-steps span { padding: 6px 8px; border-radius: 999px; background: #f1f5f9; }
.flow-steps i { width: 18px; height: 1px; background: #cbd5e1; flex-shrink: 0; }
.filter-bar { margin-bottom: 12px; }
.task-actions { display: flex; justify-content: flex-start; align-items: center; gap: 12px; white-space: nowrap; }
.task-actions :deep(.el-button + .el-button) { margin-left: 0; }
.progress-cell { display: flex; align-items: center; gap: 8px; }
.progress-text { font-size: 12px; color: var(--color-ink-tertiary); white-space: nowrap; }
.prog-ok { color: var(--color-success); } .prog-fail { color: var(--color-danger); }
.error-tag { max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: middle; }
.publish-form :deep(.el-form-item) { margin-bottom: 16px; }
.publish-tip { margin-top: 6px; color: #64748b; font-size: 12px; line-height: 1.5; }
.params-grid { width: 100%; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px 12px; align-items: center; }
.params-grid .el-checkbox { margin-right: 0; }
.content-dialog-head { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 0 0 14px; border-bottom: 1px solid var(--color-border); margin-bottom: 14px; }
.content-account { display: flex; gap: 12px; align-items: center; min-width: 0; }
.content-account strong { display: block; color: var(--color-ink); }
.content-account span { display: block; margin-top: 3px; font-size: 12px; color: var(--color-ink-tertiary); }
.content-head-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.account-post-table { width: 100%; }
.mini-metrics { display: flex; gap: 6px; flex-wrap: wrap; }
.mini-metrics span { font-size: 11px; color: var(--color-ink-secondary); background: #f1f5f9; border-radius: 999px; padding: 2px 7px; }
.detail-block { margin-bottom: 14px; }
.detail-title { font-size: 13px; font-weight: 700; color: var(--color-ink); margin-bottom: 7px; }
.detail-text { padding: 10px 12px; border-radius: 10px; background: #f8fafc; color: var(--color-ink-secondary); line-height: 1.6; max-height: 150px; overflow: auto; }
.tag-chip { margin: 0 6px 6px 0; }
.metric-cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.metric-card { padding: 10px; border: 1px solid var(--color-border); border-radius: 10px; background: #fff; text-align: center; }
.metric-card strong { display: block; font-size: 20px; color: var(--wm-primary); }
.metric-card span { font-size: 11px; color: var(--color-ink-tertiary); }
.metric-error { margin-top: 8px; font-size: 13px; }
.log-list { max-height: 200px; overflow: auto; padding: 8px; border-radius: 10px; background: #f8fafc; }
.log-item { display: flex; gap: 8px; font-size: 12px; line-height: 1.7; }
.log-item span { color: var(--color-ink-tertiary); flex-shrink: 0; }
.log-item b { color: var(--color-ink-secondary); flex-shrink: 0; }
.log-item em { font-style: normal; color: var(--color-ink-secondary); }
.log-error b { color: var(--color-danger); }
@media (max-width: 1180px) {
  .matrix-board { grid-template-columns: 1fr; }
  .matrix-side { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 980px) {
  .params-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .section-head, .content-dialog-head { flex-direction: column; align-items: stretch; }
  .auth-actions, .content-head-actions { justify-content: flex-start; }
  .metric-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .matrix-side { grid-template-columns: 1fr; }
  .account-card-grid { grid-template-columns: 1fr; }
}
</style>
