import type {
  EnvironmentServiceDefinition,
  EnvironmentTemplateManifest,
} from './environment-service'

type FieldPath = Array<string | number>
export class ManifestFieldError extends Error {
  constructor(
    public readonly path: FieldPath,
    message: string,
  ) {
    super(message)
  }
}
function fail(path: FieldPath, message: string): never {
  throw new ManifestFieldError(path, message)
}
function object(value: unknown, path: FieldPath, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(path, '请输入完整配置对象')
  const result = value as Record<string, unknown>
  const unknownKey = Object.keys(result).find((key) => !keys.includes(key))
  if (unknownKey) fail([...path, unknownKey], `模板不支持字段 ${unknownKey}`)
  return result
}
function text(value: unknown, path: FieldPath, min: number, max: number, pattern?: RegExp): string {
  if (typeof value !== 'string' || value.length < min || value.length > max)
    fail(path, `请输入${min}至${max}个字符`)
  if (pattern && !pattern.test(value)) fail(path, '字段格式不符合受控模板要求')
  return value
}
function number(value: unknown, path: FieldPath, min: number, max: number, integer = true): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max)
    fail(path, `请输入${min}至${max}之间的数值`)
  if (integer && !Number.isInteger(value)) fail(path, '请输入整数')
  return value
}
function list(value: unknown, path: FieldPath, min: number, max: number): unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max)
    fail(path, `数量应为${min}至${max}项`)
  return value
}
const serviceName = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/
const resourcePath = /^\/[^\s]*$/
const imageDigest =
  /^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?\/[a-z0-9]+(?:[._/-][a-z0-9]+)*(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?@sha256:[0-9a-f]{64}$/
const sensitiveName =
  /password|passwd|secret|token|api[_-]?key|authorization|cookie|private[_-]?key/i
function unique(values: string[], path: FieldPath) {
  if (new Set(values).size !== values.length) fail(path, '名称不能重复')
}
function readHealth(value: unknown, path: FieldPath): EnvironmentServiceDefinition['health_check'] {
  const item = object(value, path, [
    'kind',
    'path',
    'expected_status',
    'interval_seconds',
    'timeout_seconds',
    'maximum_attempts',
  ])
  if (item.kind !== 'http' && item.kind !== 'tcp') fail([...path, 'kind'], '请选择HTTP或TCP')
  if (item.kind === 'tcp' && item.path !== null) fail([...path, 'path'], 'TCP检查不接受HTTP路径')
  return {
    kind: item.kind,
    path: item.kind === 'http' ? text(item.path, [...path, 'path'], 1, 256, resourcePath) : null,
    expected_status: number(item.expected_status, [...path, 'expected_status'], 100, 599),
    interval_seconds: number(item.interval_seconds, [...path, 'interval_seconds'], 0.1, 10, false),
    timeout_seconds: number(item.timeout_seconds, [...path, 'timeout_seconds'], 0.1, 10, false),
    maximum_attempts: number(item.maximum_attempts, [...path, 'maximum_attempts'], 1, 120),
  }
}
function readVariables(value: unknown, path: FieldPath) {
  const variables = list(value, path, 0, 32).map((raw, index) => {
    const field = [...path, index]
    const item = object(raw, field, ['name', 'value'])
    const name = text(item.name, [...field, 'name'], 1, 128, /^[A-Z][A-Z0-9_]{0,127}$/)
    if (sensitiveName.test(name))
      fail([...field, 'name'], '模板不能内嵌敏感变量，请使用现有凭据配置')
    return { name, value: text(item.value, [...field, 'value'], 0, 1000) }
  })
  unique(
    variables.map((item) => item.name),
    path,
  )
  return variables
}
function readService(value: unknown, index: number): EnvironmentServiceDefinition {
  const path: FieldPath = ['services', index]
  const item = object(value, path, [
    'name',
    'image',
    'internal_port',
    'environment',
    'depends_on',
    'health_check',
    'cpu_millicores',
    'memory_megabytes',
    'pids_limit',
    'user_id',
    'group_id',
    'read_only_root_filesystem',
    'drop_all_capabilities',
    'no_new_privileges',
  ])
  const flags = ['read_only_root_filesystem', 'drop_all_capabilities', 'no_new_privileges'] as const
  for (const flag of flags) if (item[flag] !== true) fail([...path, flag], '平台安全加固必须开启')
  const dependencies = list(item.depends_on, [...path, 'depends_on'], 0, 4).map((name, i) =>
    text(name, [...path, 'depends_on', i], 1, 63, serviceName),
  )
  unique(dependencies, [...path, 'depends_on'])
  return {
    name: text(item.name, [...path, 'name'], 1, 63, serviceName),
    image: text(item.image, [...path, 'image'], 80, 500, imageDigest),
    internal_port: number(item.internal_port, [...path, 'internal_port'], 1024, 65535),
    environment: readVariables(item.environment, [...path, 'environment']),
    depends_on: dependencies,
    health_check: readHealth(item.health_check, [...path, 'health_check']),
    cpu_millicores: number(item.cpu_millicores, [...path, 'cpu_millicores'], 100, 2000),
    memory_megabytes: number(item.memory_megabytes, [...path, 'memory_megabytes'], 64, 2048),
    pids_limit: number(item.pids_limit, [...path, 'pids_limit'], 16, 256),
    user_id: number(item.user_id, [...path, 'user_id'], 1, 65535),
    group_id: number(item.group_id, [...path, 'group_id'], 1, 65535),
    read_only_root_filesystem: true,
    drop_all_capabilities: true,
    no_new_privileges: true,
  }
}
function validateTopology(services: EnvironmentServiceDefinition[]) {
  unique(
    services.map((item) => item.name),
    ['services'],
  )
  const names = new Set(services.map((item) => item.name))
  services.forEach((item, index) => {
    if (item.depends_on.some((name) => !names.has(name)))
      fail(['services', index, 'depends_on'], '依赖服务不存在，请调整依赖或恢复服务')
  })
  function visit(index: number, visiting: Set<string>): void {
    const service = services[index]
    if (visiting.has(service.name)) fail(['services', index, 'depends_on'], '服务依赖存在循环')
    const next = new Set(visiting).add(service.name)
    service.depends_on.forEach((name) =>
      visit(
        services.findIndex((item) => item.name === name),
        next,
      ),
    )
  }
  services.forEach((_, index) => visit(index, new Set()))
}
export function validateEnvironmentManifest(value: unknown): EnvironmentTemplateManifest {
  const item = object(
    value,
    [],
    ['services', 'seeds', 'default_ttl_seconds', 'maximum_ttl_seconds'],
  )
  const services = list(item.services, ['services'], 1, 5).map(readService)
  validateTopology(services)
  const seeds = list(item.seeds, ['seeds'], 0, 10).map((raw, index) => {
    const path: FieldPath = ['seeds', index]
    const seed = object(raw, path, ['profile', 'service', 'path'])
    if (seed.profile !== 'http_get_v1') fail([...path, 'profile'], '仅支持HTTP GET v1预定义任务')
    const service = text(seed.service, [...path, 'service'], 1, 63, serviceName)
    if (!services.some((entry) => entry.name === service))
      fail([...path, 'service'], 'Seed服务不存在')
    return {
      profile: 'http_get_v1' as const,
      service,
      path: text(seed.path, [...path, 'path'], 1, 256, resourcePath),
    }
  })
  const defaultTTL = number(item.default_ttl_seconds, ['default_ttl_seconds'], 60, 86400)
  const maximumTTL = number(item.maximum_ttl_seconds, ['maximum_ttl_seconds'], 60, 86400)
  if (defaultTTL > maximumTTL) fail(['default_ttl_seconds'], '默认TTL不能大于最大TTL')
  return { services, seeds, default_ttl_seconds: defaultTTL, maximum_ttl_seconds: maximumTTL }
}
export function parseEnvironmentManifest(text: string): EnvironmentTemplateManifest {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    throw new ManifestFieldError([], '请输入有效的声明式JSON模板')
  }
  return validateEnvironmentManifest(value)
}
export function defaultEnvironmentService(name = 'web'): EnvironmentServiceDefinition {
  return {
    name,
    image:
      'cgr.dev/chainguard/nginx@sha256:a104d1995e56b7a15e8f152078dfbdb1ecbf9f9d1af311e7906e7b4c0c790cf2',
    internal_port: 8080,
    environment: [{ name: 'NGINX_PORT', value: '8080' }],
    depends_on: [],
    health_check: {
      kind: 'http',
      path: '/',
      expected_status: 200,
      interval_seconds: 1,
      timeout_seconds: 2,
      maximum_attempts: 30,
    },
    cpu_millicores: 250,
    memory_megabytes: 128,
    pids_limit: 64,
    user_id: 65532,
    group_id: 65532,
    read_only_root_filesystem: true,
    drop_all_capabilities: true,
    no_new_privileges: true,
  }
}
export function defaultEnvironmentManifest(): EnvironmentTemplateManifest {
  return {
    services: [defaultEnvironmentService()],
    seeds: [{ profile: 'http_get_v1', service: 'web', path: '/' }],
    default_ttl_seconds: 3600,
    maximum_ttl_seconds: 14400,
  }
}
