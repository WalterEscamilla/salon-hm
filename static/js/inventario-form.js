"use strict";

document.querySelectorAll("[data-inventory-option]").forEach(container => {
  const select = container.querySelector("select");
  const addition = container.querySelector("[data-new-option]");
  const input = addition.querySelector("input");
  const update = () => {
    const adding = select.value === container.dataset.inventoryOption;
    addition.hidden = !adding;
    input.required = adding && !select.disabled;
  };
  select.addEventListener("change", () => {
    update();
    if (!addition.hidden) input.focus();
  });
  update();
});
