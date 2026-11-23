
import { useEffect, useState } from "react";
import { api, getToken, logout } from "./api";

import Login from "./Login";
import Register from "./Register";
import SystemStatus from "./SystemStatus";
import PhotoLibrary from "./PhotoLibrary";
import AccountSettings from "./AccountSettings";
import AdminDashboard from "./AdminDashboard";

export default function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState("Photos");
  const [navigationKey, setNavigationKey] = useState(0);
  const [registering, setRegistering] = useState(false);

  useEffect(() => {
    const handleLogout = () => {
      setUser(null);
      setPage("Photos");
      setRegistering(false);
    };

    window.addEventListener(
      "locallens:logout",
      handleLogout
    );

    if (getToken()) {
      api("/auth/me")
        .then(setUser)
        .catch(() => logout())
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }

    return () => {
      window.removeEventListener(
        "locallens:logout",
        handleLogout
      );
    };
  }, []);

  function handleLogin(account) {
    setUser(account);
    setRegistering(false);
    setPage("Photos");
  }

  if (loading) {
    return (
      <div className="loading-screen">
        Connecting to LocalLens...
      </div>
    );
  }

  if (!user) {
    return registering ? (
      <Register
        onLogin={handleLogin}
        onCancel={() => setRegistering(false)}
      />
    ) : (
      <Login
        onLogin={handleLogin}
        onRegister={() => setRegistering(true)}
      />
    );
  }

  const navigation = [
    "Photos", "Videos",
    "Albums", "Shared Albums",
    "Favorites",

    "Trash",
    "Settings",
  ];

  const adminNavigation = [
    "Administration",
    "System Status",
  ];

  function navigationButton(item) {
    return (
      <button
        key={item}
        className={
          page === item
            ? "nav-button active"
            : "nav-button"
        }
        onClick={() => {
          setPage(item);

          if (item === "Albums") {
            setNavigationKey((previous) => previous + 1);
          }
        }}
      >
        {item}
      </button>
    );
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <a className="brand" href="/">
          <span className="brand-icon">L</span>
          LocalLens
        </a>

        <div className="account-controls">
          <div>
            <strong>
              {user.display_name || user.username}
            </strong>

            <small>{user.role}</small>
          </div>

          <button
            className="secondary-button"
            onClick={logout}
          >
            Sign out
          </button>
        </div>
      </header>

      <div className="dashboard-layout">
        <aside className="sidebar">
          <p className="section-label">LIBRARY</p>

          {navigation.map(navigationButton)}

          {user.role === "admin" && (
            <>
              <p className="section-label admin-nav-label">
                ADMINISTRATION
              </p>

              {adminNavigation.map(navigationButton)}
            </>
          )}

          <div className="sidebar-version">
            LocalLens v0.3.0
            <br />
            Private by design
          </div>
        </aside>

        <main className="dashboard-content">
          {page === "Settings" ? (
            <AccountSettings
              user={user}
              onUpdate={setUser}
            />
          ) : page === "Administration" &&
              user.role === "admin" ? (
            <AdminDashboard />
          ) : page === "System Status" &&
              user.role === "admin" ? (
            <SystemStatus />
          ) : (
            <PhotoLibrary key={`${page}-${navigationKey}`} page={page} />
          )}
        </main>
      </div>
    </div>
  );
}
