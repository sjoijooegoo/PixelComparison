"""增强热力图配置应通过 API 完整持久化。"""


def test_enhanced_heatmap_settings_persist(client):
    patch = {
        "heatmap_method": "legacy",
        "heatmap_norm_scale": 96.0,
        "heatmap_gamma": 1.8,
        "heatmap_density_radius": 24.0,
        "heatmap_density_floor": 0.35,
    }

    response = client.put("/api/settings", json=patch)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert {key: saved[key] for key in patch} == patch

    loaded = client.get("/api/settings")
    assert loaded.status_code == 200, loaded.text
    assert {key: loaded.json()[key] for key in patch} == patch


def test_enhanced_heatmap_numeric_settings_are_clamped(client):
    response = client.put("/api/settings", json={
        "heatmap_norm_scale": 1,
        "heatmap_gamma": 10,
        "heatmap_density_radius": -5,
        "heatmap_density_floor": 1,
    })
    assert response.status_code == 200, response.text
    saved = response.json()
    assert {
        "heatmap_norm_scale": saved["heatmap_norm_scale"],
        "heatmap_gamma": saved["heatmap_gamma"],
        "heatmap_density_radius": saved["heatmap_density_radius"],
        "heatmap_density_floor": saved["heatmap_density_floor"],
    } == {
        "heatmap_norm_scale": 4.0,
        "heatmap_gamma": 4.0,
        "heatmap_density_radius": 0.0,
        "heatmap_density_floor": 0.9,
    }
