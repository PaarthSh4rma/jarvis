import { expect, test, type Page } from "@playwright/test";


async function ask(page: Page, prompt: string, expected: string) {
  const input = page.getByLabel("Enter a command");
  await input.pressSequentially(prompt, { delay: 28 });
  await page.waitForTimeout(140);
  await page.getByLabel("Send message").click();
  await expect(page.getByText(expected, { exact: false })).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(650);
}


test("records the trusted project-reference demo", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("SAFE DEMO WORKSPACE")).toBeVisible();
  await page.waitForTimeout(150);

  await ask(page, "what projects am I working on?", "3. ClientOps Copilot");
  await ask(page, "open the second one", "Opened ExoHunter in VS Code.");
  await ask(page, "is it clean?", "ExoHunter has no uncommitted changes.");
  await ask(
    page,
    "open the other one",
    "Which project do you mean: RaceBrain or ClientOps Copilot?",
  );

  await page.waitForTimeout(1_200);
});
