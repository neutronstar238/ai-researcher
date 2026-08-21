import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AsyncState } from "../../components/ui/AsyncState";
import { apiClient } from "../../lib/api/client";
import type { HealthResponse } from "../../lib/api/types";
import { persistThemePreference, readThemePreference, type ThemePreference } from "../../lib/theme";

const CAPABILITIES: ReadonlyArray<[keyof HealthResponse, string]> = [
  ["authentication_enabled", "身份认证"],
  ["formal_experiment_enabled", "正式实验"],
  ["result_paper_enabled", "结果论文"],
  ["self_evolution_execution_enabled", "自进化执行"],
  ["self_evolution_service_configured", "自进化服务配置"],
  ["automatic_skill_activation_enabled", "自动 Skill 激活"],
  ["batch_execution_configured", "批量执行配置"],
];

export function SettingsPage() {
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: apiClient.health });
  const [theme, setTheme] = useState<ThemePreference>(readThemePreference);
  const changeTheme = (preference: ThemePreference) => {
    setTheme(preference);
    persistThemePreference(preference);
  };

  return (
    <section className="feature-page">
      <div className="feature-heading">
        <h1>系统设置</h1>
        <p>显示当前本地服务事实，并保存此浏览器的主题偏好。</p>
      </div>
      <div className="settings-grid">
        <section className="feature-card" aria-labelledby="health-settings-heading">
          <h2 id="health-settings-heading">服务健康与能力</h2>
          <AsyncState
            loading={healthQuery.isPending}
            error={healthQuery.error}
            empty={false}
            onRetry={() => void healthQuery.refetch()}
          >
            {healthQuery.data ? (
              <>
                <dl className="compact-facts service-facts">
                  <div><dt>服务</dt><dd>{healthQuery.data.service}</dd></div>
                  <div><dt>部署范围</dt><dd>{healthQuery.data.deployment_scope}</dd></div>
                </dl>
                <table className="capability-table" aria-label="服务能力">
                  <tbody>
                    {CAPABILITIES.map(([field, label]) => (
                      <tr key={field}><th scope="row">{label}</th><td>{healthQuery.data[field] === true ? "是" : "否"}</td></tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : null}
          </AsyncState>
        </section>
        <section className="feature-card" aria-labelledby="theme-heading">
          <h2 id="theme-heading">显示主题</h2>
          <fieldset className="theme-options" role="radiogroup">
            <legend>主题</legend>
            <label><input type="radio" name="theme" value="light" checked={theme === "light"} onChange={() => changeTheme("light")} />浅色</label>
            <label><input type="radio" name="theme" value="dark" checked={theme === "dark"} onChange={() => changeTheme("dark")} />深色</label>
            <label><input type="radio" name="theme" value="system" checked={theme === "system"} onChange={() => changeTheme("system")} />跟随系统</label>
          </fieldset>
        </section>
      </div>
    </section>
  );
}
