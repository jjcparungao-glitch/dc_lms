import { Post } from "./api.js";
import { showToast } from "./toast.js";

document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();

  const external_id = document.getElementById("external_id").value;
  const password = document.getElementById("password").value;
  const loginBtn = document.getElementById("loginBtn");

  loginBtn.disabled = true;
  loginBtn.textContent = "Signing in...";

  try {
    const response = await Post("/auth/login", { external_id, password });
    console.log("Login response:", response);
    if (response.success) {
      showToast("Login successful!", "success");
      await new Promise((resolve) => setTimeout(resolve, 1500));
      window.location.href = "/dashboard";
    } else {
      console.error("Login failed:", response.message);
      showToast(response.message || "Login failed", "error");
      loginBtn.disabled = false;
      loginBtn.textContent = "Sign In";
    }
  } catch (error) {
    loginBtn.disabled = false;
    loginBtn.textContent = "Sign In";
    showToast(error.message, "error");
  }
});
