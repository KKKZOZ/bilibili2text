const DEFAULT_BACKEND_PORT = '8000'

function isValidPort(value) {
  if (!/^\d+$/.test(value)) {
    return false
  }

  const port = Number.parseInt(value, 10)
  return port >= 1 && port <= 65535
}

function parseArgs(argv) {
  const viteArgs = []

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]

    if (arg === '--backend-port' || arg === '-b') {
      const value = argv[index + 1]
      if (!value) {
        console.error('Missing value for --backend-port')
        process.exit(1)
      }
      process.env.B2T_BACKEND_PORT = value
      index += 1
      continue
    }

    if (arg.startsWith('--backend-port=')) {
      process.env.B2T_BACKEND_PORT = arg.slice('--backend-port='.length)
      continue
    }

    viteArgs.push(arg)
  }

  const backendPort = process.env.B2T_BACKEND_PORT ?? DEFAULT_BACKEND_PORT
  if (!isValidPort(backendPort)) {
    console.error(`Invalid backend port: ${backendPort}`)
    process.exit(1)
  }

  if (!viteArgs.some((arg) => arg === '--host' || arg.startsWith('--host='))) {
    viteArgs.unshift('--host')
  }

  return viteArgs
}

const viteArgs = parseArgs(process.argv.slice(2))
process.argv = [process.argv[0], process.argv[1], ...viteArgs]

await import(new URL('../node_modules/vite/bin/vite.js', import.meta.url).href)
