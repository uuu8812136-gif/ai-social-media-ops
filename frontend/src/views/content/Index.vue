<template>
  <div class="content-factory rb-enter">
    <div class="page-header">
      <div>
        <h2>内容工厂</h2>
        <span class="page-sub">AI 生成 → 风控预检 → 人工审核 → 配置发布参数 → 自动发布 → 数据回流</span>
      </div>
    </div>

    <!-- 流程步骤条 -->
    <div class="workflow-steps">
      <span class="workflow-step" :class="{ active: flowStep === 1, done: flowStep > 1 }">1. AI 生成</span>
      <span class="workflow-step" :class="{ active: flowStep === 2, done: flowStep > 2 }">2. 风控检测</span>
      <span class="workflow-step" :class="{ active: flowStep === 3, done: flowStep > 3 }">3. 审核通过</span>
      <span class="workflow-step" :class="{ active: flowStep === 4, done: flowStep > 4 }">4. 配置发布</span>
      <span class="workflow-step" :class="{ active: flowStep === 5, done: flowStep > 5 }">5. 自动发布</span>
      <span class="workflow-step" :class="{ active: flowStep === 6, done: flowStep > 6 }">6. 数据回流</span>
    </div>

    <el-tabs v-model="tab" class="factory-tabs">
      <!-- 脚本生成 -->
      <el-tab-pane label="脚本生成" name="script">
        <el-form :model="scriptForm" label-width="90px" class="gen-form panel-card">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="选题" required>
                <el-input v-model="scriptForm.topic" placeholder="如：阳台封窗隔音效果对比" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="账号" required>
                <el-select v-model="scriptForm.account_id" placeholder="选择账号" filterable style="width:100%">
                  <el-option
                    v-for="a in accounts"
                    :key="a.id"
                    :label="accountLabel(a)"
                    :value="a.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="策略">
                <el-select v-model="scriptForm.strategy_type" style="width:100%" @change="onStrategyChange">
                  <el-option label="IP 策略" value="ip" />
                  <el-option label="品牌策略" value="brand" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="时长">
                <el-select v-model="scriptForm.duration" style="width:100%">
                  <el-option label="30 秒" value="30s" />
                  <el-option label="60 秒" value="60s" />
                  <el-option label="90 秒" value="90s" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="风格">
                <el-input v-model="scriptForm.style" placeholder="如：避坑测评" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="生成数量">
                <el-input-number v-model="scriptForm.count" :min="1" :max="5" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="generateScript">AI 生成脚本</el-button>
            <el-button @click="resetScriptForm">重置</el-button>
          </el-form-item>
        </el-form>

        <el-alert
          v-if="scriptGenError"
          :title="`AI 生成失败：${scriptGenError}`"
          type="error"
          show-icon
          :closable="false"
          style="margin-bottom:12px"
        />
        <el-empty v-if="!scripts.length && !scriptGenError" description="还没有内容，点击新建开始创作">
          <el-button type="primary" @click="generateScript" :loading="loading">立即生成脚本</el-button>
          <el-button @click="tab = 'trending'">去热点选题找灵感</el-button>
        </el-empty>
        <div v-else-if="scripts.length" class="result-list">
          <el-card v-for="(s, i) in scripts" :key="i" class="content-card rb-enter" :class="'rb-delay-' + ((i % 4) + 1)" shadow="never">
            <template #header>
              <div class="card-head">
                <span class="card-title">{{ s.title }}</span>
                <el-tag size="small" :type="statusTagType(s._status || 'ai_generated')">{{ statusLabel(s._status || 'ai_generated') }}</el-tag>
              </div>
            </template>
            <div class="script-body">
              <div class="content-body-text">{{ formatGeneratedBody(s) }}</div>
              <div class="tag-row">
                <el-tag v-for="t in s.tags" :key="t" size="small" effect="plain" style="margin-right:6px">{{ t }}</el-tag>
              </div>
            </div>
            <div class="card-actions">
              <el-button v-if="s._status === 'ai_generated' || !s._status" size="small" :loading="riskLoading === s.content_id" @click="riskCheck(s)">风控检测</el-button>
              <el-button v-if="s._status === 'risk_failed'" size="small" type="primary" :loading="rewriteLoading === s.content_id" @click="rewriteRisk(s)">AI 改写并复检</el-button>
              <el-button v-if="canEdit(s._status)" size="small" @click="openEdit(s)">手动编辑</el-button>
              <el-button v-if="s._status === 'risk_checked'" size="small" type="primary" @click="updateStatus(s.content_id, 'approved', s)">审核通过</el-button>
              <el-button v-if="s._status === 'approved' || s._status === 'human_reviewed'" size="small" type="primary" @click="publishToSocial(s)">发布到社媒</el-button>
              <el-button v-if="['scheduled', 'published', 'stats_synced'].includes(s._status)" size="small" @click="router.push('/social-publish')">查看发布记录</el-button>
              <el-button size="small" text @click="copyText(s)">复制全文</el-button>
              <span v-if="nextStepHint(s._status)" class="next-step-hint">{{ nextStepHint(s._status) }}</span>
            </div>
            <div v-if="s.riskResult" class="risk-result" :class="s.riskResult.passed ? 'risk-pass' : 'risk-fail'">
              <strong>{{ s.riskResult.passed ? '风控通过' : '风控未通过' }}</strong>
              <div v-if="!s.riskResult.passed && s.riskResult.issues?.length" class="risk-issues">
                <div v-for="(issue, issueIndex) in s.riskResult.issues" :key="issueIndex">{{ issue.word || issue.message }}：{{ issue.suggestion || '请调整相关表述' }}</div>
              </div>
              <div v-if="!s.riskResult.passed && s.riskResult.suggestion" class="risk-suggestion">建议：{{ s.riskResult.suggestion }}</div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 文案生成 -->
      <el-tab-pane label="文案生成" name="copy">
        <el-form :model="copyForm" label-width="90px" class="gen-form panel-card">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="选题" required>
                <el-input v-model="copyForm.topic" placeholder="如：门窗选购指南" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="账号" required>
                <el-select v-model="copyForm.account_id" placeholder="选择账号" filterable style="width:100%">
                  <el-option
                    v-for="a in accounts"
                    :key="a.id"
                    :label="accountLabel(a)"
                    :value="a.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="策略">
                <el-select v-model="copyForm.strategy_type" style="width:100%">
                  <el-option label="IP 策略" value="ip" />
                  <el-option label="品牌策略" value="brand" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="平台">
                <el-select v-model="copyForm.platform" style="width:100%">
                  <el-option label="抖音" value="douyin" />
                  <el-option label="小红书" value="xiaohongshu" />
                  <el-option label="视频号" value="weixin_video" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="生成数量">
                <el-input-number v-model="copyForm.count" :min="1" :max="5" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="generateCopy">AI 生成文案</el-button>
          </el-form-item>
        </el-form>

        <el-alert
          v-if="copyGenError"
          :title="`AI 生成失败：${copyGenError}`"
          type="error"
          show-icon
          :closable="false"
          style="margin-bottom:12px"
        />
        <el-empty v-if="!copywriting.length && !copyGenError" description="还没有文案，点击新建开始创作">
          <el-button type="primary" @click="generateCopy" :loading="loading">立即生成文案</el-button>
          <el-button @click="tab = 'trending'">去热点选题找灵感</el-button>
        </el-empty>
        <div v-else-if="copywriting.length" class="result-list">
          <el-card v-for="(c, i) in copywriting" :key="i" class="content-card rb-enter" :class="'rb-delay-' + ((i % 4) + 1)" shadow="never">
            <template #header>
              <div class="card-head">
                <span class="card-title">{{ c.title }}</span>
                <el-tag size="small" :type="statusTagType(c._status || 'ai_generated')">{{ statusLabel(c._status || 'ai_generated') }}</el-tag>
              </div>
            </template>
            <div class="script-body">
              <p><strong>正文：</strong>{{ c.body_text || c.body }}</p>
              <div v-if="c.tags?.length" class="tag-row">
                <el-tag v-for="t in c.tags" :key="t" size="small" effect="plain" style="margin-right:6px">{{ t }}</el-tag>
              </div>
            </div>
            <div class="card-actions">
              <el-button v-if="c._status === 'ai_generated' || !c._status" size="small" :loading="riskLoading === c.content_id" @click="riskCheckCopy(c)">风控检测</el-button>
              <el-button v-if="c._status === 'risk_failed'" size="small" type="primary" :loading="rewriteLoading === c.content_id" @click="rewriteRisk(c)">AI 改写并复检</el-button>
              <el-button v-if="canEdit(c._status)" size="small" @click="openEdit(c)">手动编辑</el-button>
              <el-button v-if="c._status === 'risk_checked'" size="small" type="primary" @click="updateCopyStatus(c.content_id, 'approved', c)">审核通过</el-button>
              <el-button v-if="c._status === 'approved' || c._status === 'human_reviewed'" size="small" type="primary" @click="publishToSocial(c)">发布到社媒</el-button>
              <el-button v-if="['scheduled', 'published', 'stats_synced'].includes(c._status)" size="small" @click="router.push('/social-publish')">查看发布记录</el-button>
              <el-button size="small" text @click="copyText(c)">复制全文</el-button>
              <span v-if="nextStepHint(c._status)" class="next-step-hint">{{ nextStepHint(c._status) }}</span>
            </div>
            <div v-if="c.riskResult" class="risk-result" :class="c.riskResult.passed ? 'risk-pass' : 'risk-fail'">
              <strong>{{ c.riskResult.passed ? '风控通过' : '风控未通过' }}</strong>
              <div v-if="!c.riskResult.passed && c.riskResult.issues?.length" class="risk-issues">
                <div v-for="(issue, issueIndex) in c.riskResult.issues" :key="issueIndex">{{ issue.word || issue.message }}：{{ issue.suggestion || '请调整相关表述' }}</div>
              </div>
              <div v-if="!c.riskResult.passed && c.riskResult.suggestion" class="risk-suggestion">建议：{{ c.riskResult.suggestion }}</div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 内容列表 -->
      <el-tab-pane label="内容列表" name="list">
        <div class="filter-bar">
          <el-select v-model="listFilter.status" placeholder="状态筛选" clearable style="width:160px" @change="onFilterChange">
            <el-option label="草稿" value="draft" />
            <el-option label="AI已生成" value="ai_generated" />
            <el-option label="风控通过" value="risk_checked" />
            <el-option label="风控未通过" value="risk_failed" />
            <el-option label="已审核" value="approved" />
            <el-option label="已人工审核" value="human_reviewed" />
            <el-option label="待执行" value="scheduled" />
            <el-option label="已发布" value="published" />
            <el-option label="已回流数据" value="stats_synced" />
            <el-option label="发布失败" value="publish_failed" />
          </el-select>
          <el-select v-model="listFilter.account_id" placeholder="账号筛选" clearable filterable style="width:240px" @change="onFilterChange">
            <el-option v-for="a in accounts" :key="a.id" :label="a.account_name" :value="a.id" />
          </el-select>
          <el-button @click="loadScripts">刷新</el-button>
        </div>
        <el-table :data="scriptList" v-loading="listLoading" style="margin-top:12px">
          <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ row.content_type === 'video_script' ? '视频脚本' : '图文文案' }}</template>
          </el-table-column>
          <el-table-column label="账号" width="150">
            <template #default="{ row }">{{ accountName(row.account_id) }}</template>
          </el-table-column>
          <el-table-column prop="strategy_type" label="策略" width="90">
            <template #default="{ row }">{{ row.strategy_type === 'ip' ? 'IP' : '品牌' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="风控" width="100">
            <template #default="{ row }">
              <el-tag v-if="!row.risk_check_result" size="small" type="info">未检测</el-tag>
              <el-tag v-else :type="row.risk_check_result.passed ? 'success' : 'danger'" size="small">
                {{ row.risk_check_result.passed ? '通过' : '未通过' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="190" show-overflow-tooltip>
            <template #default="{ row }"><span style="white-space:nowrap">{{ formatTime(row.created_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="300" fixed="right" class-name="action-column">
            <template #default="{ row }">
              <el-button v-if="row.status === 'ai_generated'" link size="small" :loading="riskLoading === row.id" @click="riskCheckRow(row)">风控检测</el-button>
              <el-button v-if="row.status === 'risk_failed'" link size="small" type="primary" :loading="rewriteLoading === row.id" @click="rewriteRisk(row, true)">AI 改写并复检</el-button>
              <el-button v-if="canEdit(row.status)" link size="small" @click="openEdit(row, true)">编辑</el-button>
              <el-button v-if="row.status === 'risk_checked'" link size="small" type="primary" @click="updateRowStatus(row, 'approved')">审核通过</el-button>
              <el-button v-if="row.status === 'approved' || row.status === 'human_reviewed'" link size="small" type="primary" @click="publishToSocialRow(row)">发布到社媒</el-button>
              <el-button v-if="['scheduled', 'published', 'stats_synced'].includes(row.status)" link size="small" @click="router.push('/social-publish')">查看发布记录</el-button>
              <el-button link size="small" @click="viewDetail(row)">详情</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="还没有内容，点击新建开始创作" :image-size="60">
              <el-button type="primary" size="small" @click="tab = 'script'">去新建内容</el-button>
            </el-empty>
          </template>
        </el-table>
        <el-pagination
          v-if="listTotal > listFilter.page_size"
          style="margin-top:12px;justify-content:flex-end;display:flex"
          background
          layout="prev, pager, next"
          :total="listTotal"
          :page-size="listFilter.page_size"
          :current-page="listFilter.page"
          @current-change="onPageChange"
        />
      </el-tab-pane>

      <!-- 本地化改写 -->
      <el-tab-pane label="本地化改写" name="localize">
        <el-form :model="localizeForm" label-width="90px" class="gen-form panel-card">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="原始文案" required>
                <el-input v-model="localizeForm.content" type="textarea" :rows="4" placeholder="粘贴需要本地化改写的文案" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="目标城市" required>
                <el-select v-model="localizeForm.cities" multiple filterable allow-create style="width:100%" placeholder="输入或选择城市">
                  <el-option label="广州" value="广州" />
                  <el-option label="深圳" value="深圳" />
                  <el-option label="佛山" value="佛山" />
                  <el-option label="东莞" value="东莞" />
                  <el-option label="珠海" value="珠海" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="账号" required>
                <el-select v-model="localizeForm.account_id" placeholder="选择账号" filterable style="width:100%">
                  <el-option v-for="a in accounts" :key="a.id" :label="accountLabel(a)" :value="a.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="策略">
                <el-select v-model="localizeForm.strategy_type" style="width:100%">
                  <el-option label="IP 策略" value="ip" />
                  <el-option label="品牌策略" value="brand" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="localizeContent">AI 本地化改写</el-button>
          </el-form-item>
        </el-form>

        <el-empty v-if="!localizeResults.length" description="尚未生成改写结果" />
        <div v-else class="result-list">
          <el-card v-for="(r, i) in localizeResults" :key="i" class="content-card rb-enter" :class="'rb-delay-' + ((i % 4) + 1)" shadow="never">
            <template #header>
              <div class="card-head">
                <span class="card-title">{{ r.city }} 版本</span>
                <el-tag size="small" :type="statusTagType(r.status || 'ai_generated')">{{ statusLabel(r.status || 'ai_generated') }}</el-tag>
              </div>
            </template>
            <div class="script-body">
              <p><strong>标题：</strong>{{ r.title }}</p>
              <p><strong>正文：</strong>{{ r.body_text || r.body }}</p>
              <div v-if="r.tags?.length" class="tag-row">
                <el-tag v-for="t in r.tags" :key="t" size="small" effect="plain" style="margin-right:6px">{{ t }}</el-tag>
              </div>
            </div>
            <div class="card-actions">
              <el-button size="small" :loading="riskLoading === `localize-${i}`" @click="riskCheckText(r, i)">一键风控</el-button>
              <el-button v-if="r.status === 'risk_failed'" size="small" type="primary" :loading="rewriteLoading === r.content_id" @click="rewriteRisk(r)">AI 改写并复检</el-button>
              <el-button v-if="canEdit(r.status) && r.content_id" size="small" @click="openEdit(r)">手动编辑</el-button>
              <el-button size="small" text @click="copyText(r)">复制全文</el-button>
            </div>
            <div v-if="r.riskResult" class="risk-result" :class="r.riskResult.passed ? 'risk-pass' : 'risk-fail'">
              <strong>{{ r.riskResult.passed ? '风控通过' : '风控未通过' }}</strong>
              <div v-if="!r.riskResult.passed && r.riskResult.issues?.length" class="risk-issues">
                <div v-for="(issue, issueIndex) in r.riskResult.issues" :key="issueIndex">{{ issue.word || issue.message }}：{{ issue.suggestion || '请调整相关表述' }}</div>
              </div>
              <div v-if="!r.riskResult.passed && r.riskResult.suggestion" class="risk-suggestion">建议：{{ r.riskResult.suggestion }}</div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 热点选题 -->
      <el-tab-pane label="热点选题" name="trending">
        <div class="filter-bar">
          <el-button @click="loadTrending" :loading="trendingLoading">刷新热点</el-button>
          <span class="page-sub">仅展示真实热点源返回的数据</span>
        </div>
        <el-table :data="trending" style="margin-top:12px">
          <el-table-column prop="topic" label="选题" min-width="220" />
          <el-table-column prop="heat" label="热度" width="100">
            <template #default="{ row }">
              <el-tag :type="row.heat === '高' ? 'danger' : row.heat === '中' ? 'warning' : 'info'" size="small">{{ row.heat }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="平台" width="100">
            <template #default="{ row }">{{ { douyin: '抖音', xiaohongshu: '小红书', weixin_video: '视频号' }[row.platform] || row.platform }}</template>
          </el-table-column>
          <el-table-column prop="reason" label="推荐理由" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link size="small" type="primary" @click="useTrending(row)">用作选题</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="尚未配置实时热点源，请手动输入选题" :image-size="60">
              <el-button type="primary" size="small" @click="tab = 'script'">手动创建选题</el-button>
            </el-empty>
          </template>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="内容详情" width="640px">
      <div v-if="detail" class="detail-box">
        <p><strong>标题：</strong>{{ detail.title }}</p>
        <p><strong>策略：</strong>{{ detail.strategy_type === 'ip' ? 'IP' : '品牌' }}</p>
        <p><strong>状态：</strong><el-tag :type="statusTagType(detail.status)" size="small">{{ statusLabel(detail.status) }}</el-tag></p>
        <p><strong>正文：</strong></p>
        <div class="detail-body">{{ displayBody(detail) }}</div>
        <div v-if="detail.tags?.length" style="margin-top:8px">
          <el-tag v-for="t in detail.tags" :key="t" size="small" effect="plain" style="margin-right:6px">{{ t }}</el-tag>
        </div>
        <div v-if="detail.risk_check_result" style="margin-top:12px">
          <strong>风控结果：</strong>
          <el-tag :type="detail.risk_check_result.passed ? 'success' : 'danger'" size="small">
            {{ detail.risk_check_result.passed ? '通过' : '未通过' }}
          </el-tag>
          <div v-if="detail.risk_check_result.issues?.length" class="risk-issues-list">
            <div v-for="(iss, idx) in detail.risk_check_result.issues" :key="idx">
              <el-tag :type="iss.severity === 'high' ? 'danger' : 'warning'" size="small">{{ iss.severity }}</el-tag>
              {{ iss.word || iss.message }} — {{ iss.suggestion || '' }}
            </div>
          </div>
        </div>
        <div v-if="detail.knowledge_references && detail.knowledge_references.length" class="knowledge-references">
          <h4>知识库引用</h4>
          <div v-for="(ref, idx) in detail.knowledge_references" :key="idx" class="reference-item">
            <el-tag size="small" type="info">{{ ref.source || '知识库' }}</el-tag>
            <span class="ref-title">{{ ref.title }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="detail && canEdit(detail.status)" @click="openEdit(detail, true)">编辑内容</el-button>
        <el-button v-if="detail?.status === 'risk_failed'" type="primary" :loading="rewriteLoading === detail.id" @click="rewriteRisk(detail, true)">AI 改写并复检</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑内容" width="680px" :close-on-click-modal="false">
      <el-form :model="editForm" label-width="72px">
        <el-form-item label="标题" required>
          <el-input v-model="editForm.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input v-model="editForm.body_text" type="textarea" :rows="12" resize="vertical" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="editForm.tags" placeholder="多个标签用逗号分隔" />
        </el-form-item>
        <el-alert title="保存后旧风控结果会清除，请重新进行风控检测。" type="warning" :closable="false" show-icon />
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="saveEdit">保存修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>


<script setup>
import { onMounted, reactive, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import request from '../../utils/request'
import { errorMessageFrom } from '../../utils/errorMessage'

const router = useRouter()
const tab = ref('script')
const loading = ref(false)
const listLoading = ref(false)
const trendingLoading = ref(false)
const riskLoading = ref('')
const rewriteLoading = ref('')
const editLoading = ref(false)

const accounts = ref([])
const scripts = ref([])
const copywriting = ref([])
const localizeResults = ref([])
const scriptList = ref([])
const trending = ref([])
const listTotal = ref(0)

// AI 生成失败原因（持久展示，便于定位）
const scriptGenError = ref('')
const copyGenError = ref('')

const scriptForm = reactive({ topic: '', account_id: '', strategy_type: 'ip', duration: '30s', style: '', count: 1 })
const copyForm = reactive({ topic: '', account_id: '', strategy_type: 'ip', platform: 'douyin', count: 1 })
const localizeForm = reactive({ content: '', cities: [], account_id: '', strategy_type: 'ip' })
const listFilter = reactive({ page: 1, page_size: 20, status: '', account_id: '' })

const detailVisible = ref(false)
const detail = ref(null)
const editVisible = ref(false)
const editTarget = ref(null)
const editForm = reactive({ id: '', content_type: 'image_text', title: '', body_text: '', tags: '' })

// 流程步骤追踪
const activeWorkflowItems = computed(() => {
  if (tab.value === 'script') return scripts.value
  if (tab.value === 'copy') return copywriting.value
  if (tab.value === 'localize') return localizeResults.value
  return []
})

const flowStep = computed(() => {
  if (!activeWorkflowItems.value.length) return 1
  return Math.max(...activeWorkflowItems.value.map(item => {
    const s = item._status || item.status || 'ai_generated'
    if (s === 'stats_synced') return 6
    if (s === 'published') return 6
    if (s === 'scheduled') return 5
    if (s === 'approved' || s === 'human_reviewed') return 4
    if (s === 'risk_checked') return 3
    if (s === 'risk_failed' || s === 'ai_generated') return 2
    return 1
  }))
})

function nextStepHint(status) {
  const hints = {
    ai_generated: '下一步：点击"风控检测"检查内容合规性',
    risk_checked: '下一步：点击"审核通过"确认内容可发布',
    approved: '下一步：进入社媒矩阵选择账号、素材和发布参数',
    human_reviewed: '下一步：进入社媒矩阵选择账号、素材和发布参数',
    scheduled: '已进入发布流程，可在社媒矩阵查看任务状态',
    published: '已发布，可在社媒矩阵查看链接并同步数据',
    stats_synced: '数据已回流，可在社媒矩阵查看作品指标',
    risk_failed: '点击“AI 改写并复检”，系统会按风险原因自动修正；也可手动编辑',
  }
  return hints[status || 'ai_generated'] || ''
}

const STATUS_MAP = {
  draft: { label: '草稿', type: 'info' },
  ai_generated: { label: 'AI已生成', type: 'warning' },
  risk_checked: { label: '风控通过', type: 'success' },
  risk_failed: { label: '风控未通过', type: 'danger' },
  approved: { label: '已审核', type: 'success' },
  human_reviewed: { label: '已审核', type: 'success' },
  scheduled: { label: '待执行', type: 'warning' },
  published: { label: '已发布', type: 'primary' },
  stats_synced: { label: '已回流数据', type: 'success' },
  publish_failed: { label: '发布失败', type: 'danger' },
}
const statusLabel = (s) => STATUS_MAP[s]?.label || s
const statusTagType = (s) => STATUS_MAP[s]?.type || 'info'
const canEdit = (status) => !['scheduled', 'published', 'stats_synced'].includes(status)

const accountName = (id) => accounts.value.find((a) => a.id === id)?.account_name || '—'
const platformLabel = (p) => ({ xiaohongshu: '小红书', channels: '视频号', douyin: '抖音', kuaishou: '快手', bilibili: 'B站' }[p] || p)
const accountLabel = (a) => `${a.account_name}（${platformLabel(a.platform)}）`
const formatTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatGeneratedBody(item) {
  if (!item) return ''
  const raw = item.body_text || item.body || ''
  if (typeof raw !== 'string') return String(raw || '')
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      if (item.content_type === 'video_script' || parsed.hook || parsed.cta) {
        const lines = [
          parsed.hook ? `开场钩子：${parsed.hook}` : '',
          parsed.body ? `正文：${parsed.body}` : '',
          parsed.cta ? `行动引导：${parsed.cta}` : '',
        ].filter(Boolean)
        if (parsed.localizations && typeof parsed.localizations === 'object') {
          lines.push(`本地化建议：${Object.entries(parsed.localizations).map(([city, value]) => `${city}：${value}`).join('；')}`)
        }
        return lines.join('\n') || raw
      }
      return parsed.body_text || parsed.body || raw
    }
  } catch {
    return raw
  }
  return raw
}

function displayBody(item) {
  return formatGeneratedBody(item)
}

async function loadAccounts() {
  const res = await request.get('/social/accounts/', { params: { page_size: 100, status: 'active' } })
  accounts.value = (res.data || []).map((a) => ({
    ...a,
    account_name: a.nickname || a.user_info?.name || a.user_info?.username || a.platform_uid || platformLabel(a.platform),
  }))
  if (!scriptForm.account_id && accounts.value.length) scriptForm.account_id = accounts.value[0].id
  if (!copyForm.account_id && accounts.value.length) copyForm.account_id = accounts.value[0].id
  if (!localizeForm.account_id && accounts.value.length) localizeForm.account_id = accounts.value[0].id
}

function onStrategyChange(v) {
  scriptForm.strategy_type = v
}

async function generateScript() {
  if (!scriptForm.topic) return ElMessage.warning('请输入选题')
  if (!scriptForm.account_id) return ElMessage.warning('请选择账号')
  loading.value = true
  scriptGenError.value = ''
  try {
    const res = await request.post('/content/scripts/generate', scriptForm, { timeout: 120000 })
    scripts.value = (res.data.scripts || []).map((s) => ({ ...s, _status: s.status, riskResult: s.risk_check || null }))
    if (!scripts.value.length) {
      scriptGenError.value = 'AI 未返回任何脚本，请调整选题或重试'
    } else {
      ElMessage.success(`已生成 ${scripts.value.length} 条脚本，并完成风控预检`)
    }
  } catch (e) {
    // 拦截器已弹错误提示，这里持久化错误原因便于定位
    scriptGenError.value = errorMessageFrom(e, 'AI 生成失败，请稍后重试。', 'ai')
  } finally { loading.value = false }
}

async function generateCopy() {
  if (!copyForm.topic) return ElMessage.warning('请输入选题')
  if (!copyForm.account_id) return ElMessage.warning('请选择账号')
  loading.value = true
  copyGenError.value = ''
  try {
    const res = await request.post('/content/copywriting/generate', copyForm, { timeout: 120000 })
    copywriting.value = (res.data.copywriting || []).map((c) => ({ ...c, _status: c.status, riskResult: c.risk_check || null }))
    if (!copywriting.value.length) {
      copyGenError.value = 'AI 未返回任何文案，请调整选题或重试'
    } else {
      ElMessage.success(`已生成 ${copywriting.value.length} 条文案，并完成风控预检`)
    }
  } catch (e) {
    copyGenError.value = errorMessageFrom(e, 'AI 生成失败，请稍后重试。', 'ai')
  } finally { loading.value = false }
}

async function localizeContent() {
  if (!localizeForm.content) return ElMessage.warning('请输入原始文案')
  if (!localizeForm.cities.length) return ElMessage.warning('请选择目标城市')
  if (!localizeForm.account_id) return ElMessage.warning('请选择账号，生成结果需要归属账号才能继续审核发布')
  loading.value = true
  try {
    const res = await request.post('/content/copywriting/localize', localizeForm, { timeout: 120000 })
    localizeResults.value = (res.data.localizations || []).map((r) => ({ ...r, riskResult: r.risk_check || null }))
    ElMessage.success(`已生成 ${localizeResults.value.length} 个城市版本`)
  } finally { loading.value = false }
}

async function riskCheckText(item, index) {
  riskLoading.value = `localize-${index}`
  try {
    const res = item.content_id
      ? await request.post(`/content/copywriting/${item.content_id}/risk-check`)
      : await request.post('/risk/check', { content: item.body_text || item.body || item.title || '' })
    item.riskResult = res.data
    item.status = res.data.passed ? 'risk_checked' : 'risk_failed'
    if (res.data.passed) ElMessage.success('风控通过')
    else ElMessage.warning('风控未通过，请修改')
  } finally { riskLoading.value = '' }
}

function resetScriptForm() {
  scriptForm.topic = ''
  scriptForm.style = ''
  scripts.value = []
  scriptGenError.value = ''
}

async function riskCheck(item) {
  const id = item.content_id || item.id
  if (!id) return ElMessage.warning('内容ID缺失，无法检测')
  riskLoading.value = id
  try {
    const res = await request.post(`/content/scripts/${id}/risk-check`)
    item.riskResult = res.data
    if (res.data.passed) {
      item._status = 'risk_checked'
      ElMessage.success('风控通过')
    } else {
      item._status = 'risk_failed'
      ElMessage.warning('风控未通过，请修改')
    }
  } finally { riskLoading.value = '' }
}

async function riskCheckCopy(item) {
  const id = item.content_id || item.id
  if (!id) return ElMessage.warning('内容ID缺失，无法检测')
  riskLoading.value = id
  try {
    const res = await request.post(`/content/copywriting/${id}/risk-check`)
    item.riskResult = res.data
    if (res.data.passed) {
      item._status = 'risk_checked'
      ElMessage.success('风控通过')
    } else {
      item._status = 'risk_failed'
      ElMessage.warning('风控未通过，请修改')
    }
  } finally { riskLoading.value = '' }
}

async function riskCheckRow(row) {
  riskLoading.value = row.id
  try {
    const url = row.content_type === 'video_script' ? `/content/scripts/${row.id}/risk-check` : `/content/copywriting/${row.id}/risk-check`
    const res = await request.post(url)
    row.risk_check_result = res.data
    row.status = res.data.passed ? 'risk_checked' : 'risk_failed'
    if (res.data.passed) ElMessage.success('风控通过')
    else ElMessage.warning('风控未通过，请修改')
  } finally { riskLoading.value = '' }
}

function applyContentResult(item, content, riskResult) {
  item.title = content.title
  item.body_text = content.body_text
  item.tags = content.tags || []
  item.status = content.status
  item._status = content.status
  item.riskResult = riskResult ?? content.risk_check_result ?? null
  item.risk_check_result = riskResult ?? content.risk_check_result ?? null
}

async function rewriteRisk(item) {
  const id = item.content_id || item.id
  if (!id) return ElMessage.warning('内容尚未保存，无法执行 AI 风控改写')
  rewriteLoading.value = id
  try {
    const res = await request.post(`/content/items/${id}/rewrite-risk`, { max_attempts: 3, platform: item.platform || null }, { timeout: 180000 })
    applyContentResult(item, res.data.content, res.data.risk_result)
    if (res.data.passed) {
      ElMessage.success(`AI 已完成改写并通过风控，共执行 ${res.data.attempts.length} 次`)
    } else {
      ElMessage.warning('AI 已尝试 3 次，仍有风险项。请手动编辑后重新检测。')
    }
  } finally {
    rewriteLoading.value = ''
  }
}

function inferContentType(item) {
  if (item.content_type) return item.content_type
  return scripts.value.includes(item) ? 'video_script' : 'image_text'
}

function openEdit(item) {
  editTarget.value = item
  editForm.id = item.content_id || item.id
  editForm.content_type = inferContentType(item)
  editForm.title = item.title || ''
  editForm.body_text = formatGeneratedBody(item)
  editForm.tags = (item.tags || []).join('，')
  detailVisible.value = false
  editVisible.value = true
}

async function saveEdit() {
  if (!editForm.title.trim()) return ElMessage.warning('标题不能为空')
  if (!editForm.body_text.trim()) return ElMessage.warning('正文不能为空')
  editLoading.value = true
  try {
    const url = editForm.content_type === 'video_script'
      ? `/content/scripts/${editForm.id}`
      : `/content/copywriting/${editForm.id}`
    const tags = editForm.tags.split(/[,，、\s]+/).map((tag) => tag.replace(/^#/, '').trim()).filter(Boolean)
    const res = await request.put(url, { title: editForm.title.trim(), body_text: editForm.body_text.trim(), tags })
    applyContentResult(editTarget.value, res.data, null)
    editVisible.value = false
    ElMessage.success('已保存修改，请重新进行风控检测')
  } finally {
    editLoading.value = false
  }
}

async function updateStatus(contentId, status, item) {
  if (!(await confirmApproval())) return
  await request.put(`/content/scripts/${contentId}`, { status })
  ElMessage.success('审核已通过，请点击“发布到社媒”继续配置发布任务')
  item._status = status
}

async function updateCopyStatus(contentId, status, item) {
  if (!(await confirmApproval())) return
  await request.put(`/content/copywriting/${contentId}`, { status })
  ElMessage.success('审核已通过，请点击“发布到社媒”继续配置发布任务')
  item._status = status
}

async function updateRowStatus(row, status) {
  if (!(await confirmApproval())) return
  const url = row.content_type === 'video_script' ? `/content/scripts/${row.id}` : `/content/copywriting/${row.id}`
  await request.put(url, { status })
  ElMessage.success('审核已通过')
  loadScripts()
}

async function confirmApproval() {
  try {
    await ElMessageBox.confirm(
      '通过后，内容将进入发布配置阶段，可继续选择社媒账号、素材和发布参数。',
      '确认审核通过？',
      {
        type: 'success',
        customClass: 'review-confirm-box',
        confirmButtonText: '确认通过',
        cancelButtonText: '再检查一下',
        closeOnClickModal: false,
        autofocus: false,
      },
    )
    return true
  } catch (action) {
    if (action !== 'cancel' && action !== 'close') throw action
    return false
  }
}

function publishToSocial(item) {
  const id = item.content_id || item.id
  router.push({ path: '/social-publish', query: { content_id: id } })
}

function publishToSocialRow(row) {
  router.push({ path: '/social-publish', query: { content_id: row.id } })
}

function onFilterChange() {
  listFilter.page = 1
  loadScripts()
}

async function loadScripts() {
  listLoading.value = true
  try {
    const params = { page: listFilter.page, page_size: listFilter.page_size }
    if (listFilter.status) params.status = listFilter.status
    if (listFilter.account_id) params.account_id = listFilter.account_id
    const res = await request.get('/content/', { params })
    scriptList.value = res.data || []
    listTotal.value = res.pagination?.total || 0
  } finally { listLoading.value = false }
}

function onPageChange(p) {
  listFilter.page = p
  loadScripts()
}

async function loadTrending() {
  trendingLoading.value = true
  try {
    const res = await request.get('/content/trending')
    trending.value = res.data.topics || []
  } finally { trendingLoading.value = false }
}

function useTrending(row) {
  scriptForm.topic = row.topic
  tab.value = 'script'
  ElMessage.success('已填入选题，请切换到脚本生成')
}

function viewDetail(row) {
  detail.value = row
  detailVisible.value = true
}

function copyText(item) {
  const text = [item.title, item.hook || '', formatGeneratedBody(item), item.cta || '', (item.tags || []).join(' ')].filter(Boolean).join('\n')
  navigator.clipboard.writeText(text)
    .then(() => ElMessage.success('已复制到剪贴板'))
    .catch(() => ElMessage.error('复制失败，请手动选择文本复制'))
}

onMounted(async () => {
  await loadAccounts()
  loadScripts()
})
</script>

<style scoped>
.content-factory { padding: 0; }
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0 0 4px; font-size: 24px; font-weight: 800; letter-spacing: -0.02em; }
.page-sub { color: var(--color-ink-tertiary); font-size: 13px; }

/* 流程步骤条 */
.workflow-steps { display: flex; gap: 6px; padding: 12px 16px; margin-bottom: 16px; flex-wrap: wrap; border-radius: var(--radius-lg); }
.workflow-step {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 500;
  color: var(--color-ink-tertiary);
  background: var(--color-surface-subtle);
  transition: all 0.3s cubic-bezier(0.34,1.56,0.64,1);
}
.workflow-step.active {
  color: #fff;
  background: linear-gradient(135deg, #0f6bc5, #3b9eff);
  box-shadow: 0 4px 12px rgba(15,107,197,0.35);
  transform: translateY(-2px);
}
.workflow-step.done {
  color: var(--color-success);
  background: rgba(13,150,104,0.10);
}

/* 下一步提示 */
.next-step-hint {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background: rgba(15,107,197,0.06);
  border: 1px solid rgba(15,107,197,0.15);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--color-accent);
  white-space: nowrap;
}

.gen-form.panel-card { padding: 16px; margin-bottom: 16px; border-radius: var(--radius-lg); }
.result-list { display: flex; flex-direction: column; gap: 12px; }
.content-card { border-radius: var(--radius-lg) !important; }
.content-card .card-head { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-weight: 600; color: var(--color-ink); }
.script-body p { margin: 6px 0; line-height: 1.7; color: var(--color-ink-secondary); }
.script-body strong { color: var(--color-ink); }
.content-body-text { white-space: pre-wrap; line-height: 1.75; color: var(--color-ink-secondary); overflow-wrap: anywhere; }
.tag-row { margin-top: 8px; }
.card-actions { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.risk-result { margin-top: 10px; padding: 8px 12px; border-radius: var(--radius-sm); font-size: 13px; }
.risk-pass { background: rgba(13,150,104,0.08); color: #0d9668; }
.risk-fail { background: rgba(220,38,38,0.08); color: #dc2626; }
.risk-issues { margin-top: 6px; line-height: 1.7; }
.risk-suggestion { margin-top: 6px; font-weight: 500; }
.filter-bar { display: flex; gap: 12px; align-items: center; }
:deep(.el-table__cell.el-table-fixed-column--right) { background: var(--color-surface, #fff) !important; }
:deep(.el-table__body .action-column .cell) { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; }
:deep(.el-table__body .action-column .el-button + .el-button) { margin-left: 0; }
.detail-box p { margin: 8px 0; line-height: 1.7; color: var(--color-ink-secondary); }
.detail-box strong { color: var(--color-ink); }
.detail-body { background: var(--color-surface-subtle); padding: 12px; border-radius: var(--radius-sm); white-space: pre-wrap; line-height: 1.7; color: var(--color-ink-secondary); }
.risk-issues-list { margin-top: 8px; font-size: 13px; line-height: 2; }

/* knowledge-references */
.knowledge-references { margin-top: 16px; padding: 12px; background: var(--color-surface-subtle); border-radius: var(--radius-md); border: 1px solid var(--color-border); }
.knowledge-references h4 { margin: 0 0 8px; font-size: 14px; color: var(--color-ink); }
.reference-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
.ref-title { color: var(--color-ink-secondary); }

@media (max-width: 768px) {
  .workflow-steps { padding: 10px; }
  .workflow-step { flex: 1 1 calc(33.333% - 6px); text-align: center; }
  .filter-bar { align-items: stretch; flex-direction: column; }
  :deep(.el-dialog) { width: calc(100% - 24px) !important; }
}
</style>
