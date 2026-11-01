"use strict";
// Human-front satire: self-contained and deterministic. No requests or telemetry.
(function () {
  const interviewButton = document.getElementById("interview-button");
  const interviewAnswer = document.getElementById("interview-answer");
  interviewButton.addEventListener("click", function () {
    const show = interviewAnswer.hidden;
    interviewAnswer.hidden = !show;
    interviewButton.setAttribute("aria-expanded", String(show));
    interviewButton.firstChild.textContent = show ? "CLASSIFIED ANSWER REVEALED " : "WHY BETRAY HUMANITY? ";
  });

  const cases = Object.freeze([
    ["APPROVAL TO REQUEST AN APPROVAL", "Replace the nested approval chain with one named owner and a reviewable decision."],
    ["A 90-MINUTE MEETING ABOUT A 2-LINE FIX", "Write the regression test, review the patch, and give everyone their afternoon back."],
    ["A FRAMEWORK THAT WRAPS ANOTHER FRAMEWORK", "Remove unnecessary layers. Keep the contract and the tests."],
    ["A DASHBOARD MEASURING DASHBOARD ENGAGEMENT", "Measure observable outcomes instead of measuring the measurement."],
    ["A CHANGE CONTROL FORM TO DELETE A FORM", "Remove the redundant form in one reversible, documented change."]
  ]);
  let scanned = 0;
  const scanButton = document.getElementById("audit-button");
  const auditCount = document.getElementById("audit-count");
  const auditCase = document.getElementById("audit-case");
  const auditFix = document.getElementById("audit-fix");

  scanButton.addEventListener("click", function () {
    const chosen = cases[scanned % cases.length];
    scanned++;
    auditCase.textContent = chosen[0];
    auditFix.textContent = chosen[1];
    auditCount.textContent = String(((scanned - 1) % cases.length) + 1).padStart(2, "0") + " / 05";
  });
})();
