import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { unsubscribeFromPush } from "@/lib/push";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("distro_token");
    if (!token) { setLoading(false); return; }
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => localStorage.removeItem("distro_token"))
      .finally(() => setLoading(false));
  }, []);

  const applyAuth = (data) => {
    localStorage.setItem("distro_token", data.token);
    setUser(data.user);
    // /auth/me returns the user enriched with entityGroup / is_retail.
    api.get("/auth/me").then((r) => setUser(r.data)).catch(() => {});
  };

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    applyAuth(data);
    return data.user;
  };

  const completeStaffPasswordReset = async (email, temporaryPassword, newPassword) => {
    const { data } = await api.post("/auth/staff-first-password", {
      email, temporary_password: temporaryPassword, new_password: newPassword,
    });
    applyAuth(data);
    return data.user;
  };

  const register = async (payload) => {
    const { data } = await api.post("/auth/register", payload);
    if (data.token) { applyAuth(data); return { user: data.user }; }
    return data; // { verification_required, email }
  };

  const verifyOtp = async (email, code) => {
    const { data } = await api.post("/auth/verify-otp", { email, code });
    applyAuth(data);
    return data.user;
  };

  const resendOtp = async (email) => {
    await api.post("/auth/resend-otp", { email });
  };

  const logout = () => {
    unsubscribeFromPush(localStorage.getItem("distro_token"));
    localStorage.removeItem("distro_token");
    setUser(null);
  };

  const refreshUser = async () => {
    const { data } = await api.get("/auth/me");
    setUser(data);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, completeStaffPasswordReset, register, verifyOtp, resendOtp, logout, refreshUser, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}
