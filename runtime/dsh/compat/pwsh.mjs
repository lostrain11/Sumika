// DSH's Windows sandbox does not preserve pwsh's initial location reliably.
// Use PowerShell's native startup option; keep DSH confinement and approvals.
import { SandboxPwshExecutor } from '@deepseek-ai/dsh-pwsh-sandbox';

export default class WorkspacePwshExecutor extends SandboxPwshExecutor {
  argv(spec) {
    const argv = super.argv(spec);
    return [argv[0], '-WorkingDirectory', spec.workdir, ...argv.slice(1)];
  }
export const name = 'sumika-pwsh-working-directory';
