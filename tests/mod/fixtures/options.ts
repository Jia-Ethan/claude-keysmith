// tools/test_mod.py changes defaults in an isolated plugin copy for each variant.
import type { Options } from '../../../hooks/prompts'
const options: Options = { mode: 'runtime', rulesFile: '', appendFile: '', registerAgent: true }
export default options
