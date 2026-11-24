import axe from 'axe-core';

/**
 * Run axe-core on a rendered component and fail with a readable list of violations.
 *
 *   const { container } = render(<Page />);
 *   await screen.findByRole('heading', { name: 'Sign in' }); // wait until it has loaded
 *   await expectNoA11yViolations(container);
 */
export async function expectNoA11yViolations(container: Element): Promise<void> {
  const results = await axe.run(container, {
    rules: {
      // jsdom does not lay out or paint, so axe cannot measure contrast here.
      'color-contrast': { enabled: false },
      // A page test renders one page without the app's <main> and <h1> layout around it,
      // so landmark and page-level heading rules would fire on every test, not on real pages.
      region: { enabled: false },
      'page-has-heading-one': { enabled: false },
      'landmark-one-main': { enabled: false },
    },
  });
  if (results.violations.length === 0) return;

  const report = results.violations
    .map((v) => {
      const nodes = v.nodes.map((n) => `    - ${n.target.join(' ')}: ${n.failureSummary?.split('\n').join(' ')}`);
      return `${v.id} (${v.impact ?? 'unknown'}): ${v.help}\n  ${v.helpUrl}\n${nodes.join('\n')}`;
    })
    .join('\n\n');
  throw new Error(`Accessibility violations found:\n\n${report}`);
}
