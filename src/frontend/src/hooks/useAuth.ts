import { useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../services/api";
import type { AuthToken } from "../types";

export function useAuth() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const loginFn = async (email: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const { data }: { data: AuthToken } = await api.login(email, password);
      localStorage.setItem("lk_token", data.access_token);
      localStorage.setItem("lk_user", JSON.stringify({ id: data.user_id, display_name: data.display_name }));
      navigate(data.access_granted ? "/dashboard" : "/subscribe");
    } catch {
      setError("Invalid email or password");
    } finally {
      setLoading(false);
    }
  };

  const registerFn = async (email: string, password: string, display_name: string, promoCode?: string) => {
    setLoading(true);
    setError(null);
    try {
      const { data }: { data: AuthToken } = await api.register(email, password, display_name, promoCode);
      localStorage.setItem("lk_token", data.access_token);
      localStorage.setItem("lk_user", JSON.stringify({ id: data.user_id, display_name: data.display_name }));
      // A valid promo code grants access immediately; otherwise the account
      // exists but is gated until checkout completes.
      navigate(data.access_granted ? "/dashboard" : "/subscribe");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Registration failed. Email may already be in use.");
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("lk_token");
    localStorage.removeItem("lk_user");
    navigate("/login");
  };

  const getUser = () => {
    const raw = localStorage.getItem("lk_user");
    return raw ? JSON.parse(raw) : null;
  };

  return { loginFn, registerFn, logout, getUser, loading, error };
}
