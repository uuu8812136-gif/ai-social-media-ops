const DEFAULT_MESSAGE = '操作没有完成，请稍后重试。'

const FIELD_LABELS = {
  account_id: '账号',
  account_ids: '账号',
  api_key: 'API Key',
  base_url: 'API 地址',
  content: '内容',
  description: '正文',
  file: '文件',
  media_paths: '素材',
  model: '模型名称',
  name: '名称',
  password: '密码',
  platform: '平台',
  scheduled_at: '定时时间',
  strategy_type: '运营策略',
  title: '标题',
  topic: '选题',
  username: '用户名',
}

const STATUS_MESSAGES = {
  400: '提交的信息不符合要求，请检查后重试。',
  401: '登录已过期，请重新登录。',
  403: '当前账号没有执行此操作的权限，请联系管理员。',
  404: '没有找到要操作的数据，可能已被删除，请刷新页面。',
  409: '这条数据已经存在或已被其他人修改，请刷新后重试。',
  413: '上传的文件太大，请压缩文件或选择较小的文件。',
  422: '提交的信息不完整，请检查必填项和填写格式。',
  429: '操作太频繁，请稍等一会儿再试。',
  500: '服务器处理失败，请稍后重试；如果一直失败，请联系管理员。',
  502: '暂时无法连接外部服务，请稍后重试。',
  503: '服务正在启动或维护，请稍后重试。',
  504: '外部服务响应太慢，请稍后重试。',
}

function fieldLabel(field) {
  return FIELD_LABELS[field] || field || '相关信息'
}

function validationMessage(items) {
  if (!Array.isArray(items) || !items.length) return ''
  const messages = items.slice(0, 3).map((item) => {
    const field = fieldLabel(item?.loc?.slice(-1)?.[0])
    const type = String(item?.type || '').toLowerCase()
    const msg = String(item?.msg || '').toLowerCase()
    if (type.includes('missing') || msg.includes('field required')) return `请填写${field}`
    if (type.includes('uuid')) return `${field}选择无效，请重新选择`
    if (type.includes('string_too_short')) return `${field}填写得太短`
    if (type.includes('string_too_long')) return `${field}填写得太长`
    if (type.includes('greater_than') || type.includes('less_than')) return `${field}超出允许范围`
    return `${field}填写不正确`
  })
  return `${messages.join('；')}。`
}

function extractMessage(input) {
  if (input == null) return ''
  if (typeof input === 'string' || typeof input === 'number') return String(input).trim()
  if (Array.isArray(input)) return validationMessage(input)
  if (typeof input !== 'object') return String(input).trim()

  if (input.userMessage) return String(input.userMessage).trim()
  const responseData = input.response?.data
  const detail = responseData?.detail ?? input.detail
  if (Array.isArray(detail)) return validationMessage(detail)
  const candidate = responseData?.message ?? detail ?? input.message ?? input.error
  if (candidate && typeof candidate === 'object') {
    if (Array.isArray(candidate)) return validationMessage(candidate)
    return JSON.stringify(candidate)
  }
  return String(candidate || '').trim()
}

function hasAny(text, patterns) {
  return patterns.some((pattern) => text.includes(pattern))
}

function finish(message) {
  const compact = String(message || '').replace(/\s+/g, ' ').trim()
  return compact.length > 180 ? `${compact.slice(0, 180)}...` : compact
}

export function humanizeError(input, options = {}) {
  const status = Number(options.status || input?.response?.status || 0)
  const context = options.context || 'general'
  const fallback = options.fallback || STATUS_MESSAGES[status] || DEFAULT_MESSAGE
  const raw = extractMessage(input)
  if (!raw) return fallback

  const lower = raw.toLowerCase()

  if (hasAny(lower, ['historical task was not found', 'not found in the platform creator content list'])) {
    return '平台后台没有找到这条历史发布记录，请重新发布后再管理。'
  }
  if (hasAny(lower, ['publish_unknown', 'publish result unknown'])) {
    return '平台没有返回明确的发布结果，请到平台后台确认；确认无记录后再重新发布。'
  }
  if (hasAny(lower, ['needs_phone_captcha', 'phone captcha required', 'verification code required'])) {
    return '平台要求输入手机验证码，系统已打开真实平台窗口，请在该窗口完成验证；验证通过后会自动继续发布。'
  }
  if (hasAny(lower, ['needs_human_captcha', 'human captcha required', 'slider verification', '人机验证'])) {
    return '平台触发了人机验证，系统已打开真实平台窗口，请在该窗口完成验证；验证通过后会自动继续发布。'
  }
  if (hasAny(lower, ['verification timeout', 'verification timed out', '验证超时'])) {
    return '验证等待超时，请重新发起发布任务。'
  }
  if (hasAny(lower, ['verification dismissed', 'verification cancelled', '已取消验证'])) {
    return '验证已被取消，任务标记为失败。'
  }
  if (hasAny(lower, ['nosuchkey', 'no such key', 'specified key does not exist', 'file not found', 'enoent'])) {
    return '素材文件已经不存在，请重新上传素材后再操作。'
  }
  if (hasAny(lower, ['accessdenied', 'minio', 'amazon s3', 'signaturedoesnotmatch'])) {
    return '系统读取素材失败，文件权限可能已经失效，请重新上传素材后再发布。'
  }
  if ((lower.includes('403') || lower.includes('forbidden')) && context === 'publish') {
    return '平台拒绝了本次操作，账号登录状态或发布权限可能已失效，请先校验账号后重试。'
  }
  if ((lower.includes('403') || lower.includes('forbidden')) && context === 'upload') {
    return '素材上传或读取权限已失效，请重新登录后再上传。'
  }
  if (lower.includes('403') || lower.includes('forbidden')) {
    return STATUS_MESSAGES[403]
  }
  if (hasAny(lower, ['401', 'unauthorized', 'not authenticated', 'authentication required'])) {
    return context === 'ai'
      ? 'AI 模型密钥无效或没有该模型权限，请管理员检查模型配置。'
      : '登录状态已经失效，请重新登录后再操作。'
  }
  if (hasAny(lower, ['cookie expired', 'cookie is invalid', 'invalid cookie', 'cookie_missing', 'cookie missing'])) {
    return '社媒账号登录已经失效，请重新扫码授权。'
  }
  if (hasAny(lower, ['media_required', 'media required', 'missing media', 'no media'])) {
    return '还没有选择可发布的素材，请先上传或选择图片/视频。'
  }
  if (hasAny(lower, ['login failed', 'sign in failed', '扫码登录失败'])) {
    return '社媒账号登录失败，请重新获取二维码并扫码授权。'
  }
  if (hasAny(lower, ['publish failed', 'failed to publish', '发布失败'])) {
    return '内容发布失败，请先校验账号和素材，再重新发布。'
  }
  if (hasAny(lower, ['upload failed', 'failed to upload'])) {
    return '素材上传失败，请检查文件格式和网络后重试。'
  }
  if (hasAny(lower, ['download failed', 'failed to download'])) {
    return '文件下载失败，请刷新页面后重试。'
  }
  if (hasAny(lower, ['crawl failed', 'crawler failed', 'collection failed', '采集失败'])) {
    return '数据采集没有完成，请检查账号登录状态和网络后重试。'
  }
  if (hasAny(lower, ['worker not running', 'no workers available', 'connection to redis lost', 'broker connection'])) {
    return '后台任务服务暂未运行，请联系管理员启动任务服务。'
  }
  if (hasAny(lower, ['err_name_not_resolved', 'err_connection_closed', 'err_connection_reset', 'err_internet_disconnected', 'network error'])) {
    return context === 'login'
      ? '暂时无法打开平台登录页，请检查网络后重新获取二维码。'
      : '网络连接中断，请检查网络后重试。'
  }
  if (hasAny(lower, ['econnrefused', 'connection refused', 'failed to connect', 'cannot connect', '无法连接'])) {
    return '暂时无法连接服务，请确认服务已启动并稍后重试。'
  }
  if (hasAny(lower, ['timeout', 'timed out', 'econnaborted', '504 gateway'])) {
    return context === 'login'
      ? '平台登录页加载太慢，请检查网络后重新获取二维码。'
      : '操作等待时间过长，请稍后重试。'
  }
  if (hasAny(lower, ["executable doesn't exist", 'chromium_headless_shell', 'playwright install', 'browser was not found'])) {
    return '自动化浏览器没有正确安装，请联系管理员重新部署服务。'
  }
  if (hasAny(lower, ['target page, context or browser has been closed', 'target closed', 'browser closed', 'page closed'])) {
    return '自动化页面意外关闭，请重新执行操作。'
  }
  if (hasAny(lower, ['selector', 'locator', 'element not found', 'waiting for element', 'strict mode violation'])) {
    return '平台页面可能已经改版，系统暂时无法完成操作，请联系管理员更新自动化规则。'
  }
  if (hasAny(lower, ['page.goto', 'navigation failed', 'navigation error', 'frame was detached'])) {
    return '平台页面加载失败，请检查网络后重试；仍然失败时请联系管理员。'
  }
  if (hasAny(lower, ['qr code not found', 'qrcode not found', '二维码获取失败', '未找到二维码'])) {
    return '没有读取到登录二维码，请重试；仍然失败时请检查平台登录页是否正常。'
  }
  if (hasAny(lower, ['unsupportedmodel', 'unsupported model', 'model not found'])) {
    return '当前模型名称不可用，请管理员到“模型配置”选择有权限的模型。'
  }
  if (lower.includes('api key') && hasAny(lower, ['invalid', 'unauthorized', '无效', '权限'])) {
    return 'AI 模型密钥无效或没有该模型权限，请管理员检查模型配置。'
  }
  if (hasAny(lower, ['模型未配置', 'ai model is not configured', 'llm is not configured'])) {
    return 'AI 模型尚未配置，请管理员先完成“模型配置”。'
  }
  if (hasAny(lower, ['未返回可用内容', 'empty model response', 'empty response from model'])) {
    return 'AI 模型没有返回有效内容，请调整选题后重试。'
  }
  if (hasAny(lower, ['quota', 'insufficient balance', 'insufficient_quota', 'rate limit', 'too many requests']) || status === 429) {
    return context === 'ai'
      ? 'AI 模型额度不足或请求过多，请检查余额或稍后重试。'
      : STATUS_MESSAGES[429]
  }
  if (hasAny(lower, ['invalid json', 'jsondecodeerror', 'unexpected token', 'cannot parse', '无法解析'])) {
    return '服务返回的数据格式异常，请稍后重试。'
  }
  if (hasAny(lower, ['unsupported platform', 'platform not supported', 'factory returned none', 'returned none'])) {
    return '该平台功能暂未接入或正在维护，请选择其他平台。'
  }
  if (hasAny(lower, ['unsupported file', 'invalid file type', 'unsupported format', 'codec', 'ffmpeg'])) {
    return '素材格式暂不支持，请转换为常用的 JPG、PNG 或 MP4 格式后重试。'
  }
  if (hasAny(lower, ['content violation', 'moderation failed', 'sensitive content', 'risk check failed'])) {
    return '内容可能不符合平台规则，请修改敏感词、标题或素材后重试。'
  }
  if (hasAny(lower, ['unique constraint', 'duplicate key', 'already exists'])) {
    return '相同数据已经存在，请勿重复添加。'
  }
  if (hasAny(lower, ['foreign key constraint', 'integrityerror'])) {
    return '这条数据仍被其他内容使用，暂时不能删除或修改。'
  }
  if (hasAny(lower, ['payload too large', 'request entity too large']) || status === 413) {
    return STATUS_MESSAGES[413]
  }
  if (/\b404\b/.test(lower) || lower.includes('not found')) {
    return context === 'publish'
      ? '平台上的内容或页面已经不存在，请刷新任务状态。'
      : STATUS_MESSAGES[404]
  }
  if (/\b5\d\d\b/.test(lower) || lower.includes('internal server error')) {
    return STATUS_MESSAGES[500]
  }
  if (Array.isArray(input?.response?.data?.detail) || Array.isArray(input?.detail)) {
    return validationMessage(input?.response?.data?.detail || input.detail) || STATUS_MESSAGES[422]
  }

  const containsChinese = /[\u4e00-\u9fff]/.test(raw)
  const containsTechnicalTrace = hasAny(lower, [
    'traceback', 'stack trace', 'sqlalchemy', 'pydantic', 'playwright',
    ' at /app/', ' at c:\\', 'node_modules', 'exception:',
  ])
  if (containsChinese && !containsTechnicalTrace) {
    return finish(raw
      .replace(/https?:\/\/\S+/gi, '平台页面')
      .replace(/\b(?:HTTP Error|Error|Exception)\b:?/gi, '')
    )
  }

  if (status >= 500) return STATUS_MESSAGES[status] || STATUS_MESSAGES[500]
  if (status && STATUS_MESSAGES[status] && !containsChinese) return STATUS_MESSAGES[status]

  return fallback
}

export function errorMessageFrom(error, fallback, context = 'general') {
  return humanizeError(error, {
    status: error?.response?.status || error?.status,
    fallback: fallback || DEFAULT_MESSAGE,
    context,
  })
}
