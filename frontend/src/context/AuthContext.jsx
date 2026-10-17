import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

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
  };

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    applyAuth(data);
    return data.user;
  };

  const register = async (payload) => {
    const { data } = await api.post("/auth/register", payload);
    applyAuth(data);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem("distro_token");
    setUser(null);
  };

  const refreshUser = async () => {
    const { data } = await api.get("/auth/me");
    setUser(data);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}
