"""설정 로드 테스트."""
from __future__ import annotations

import os

from src.housing.config import load_config, Config


class TestConfig:
    def test_load_default_config(self, tmp_path):
        """기본 config.yaml 정상 파싱."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        assert os.path.exists(config_path)
        config = load_config(config_path)
        assert "api_keys" in config
        assert "weights" in config
        assert config["weights"]["discount_rate"] == 0.35

    def test_config_class(self):
        """Config 클래스 정상 동작."""
        config = Config()
        # 환경변수 미설정시 ${DATA_GO_KR_API_KEY} 문자 그대로 유지
        assert "${DATA_GO_KR_API_KEY}" in config.data_go_kr_key
        assert config.weights["discount_rate"] == 0.35
        assert config.request_delay == 0.5
        assert config.max_retries == 3
        assert config.timeout == 30
        assert config.per_page == 100
        assert config.cache_enabled is True

    def test_env_substitution(self, monkeypatch, tmp_path):
        """환경변수 치환 검증."""
        monkeypatch.setenv("TEST_KEY", "test_value_123")
        yaml_content = "test_key: ${TEST_KEY}\nstatic: hello\n"
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(yaml_content)

        config = load_config(str(config_path))
        assert config["test_key"] == "test_value_123"
        assert config["static"] == "hello"

    def test_config_class_accessor(self):
        """Config 접근자 메서드 검증."""
        config = Config()
        assert "data_go_kr" in config.api_keys
        assert config.brand_score_overrides == {}
        assert config.region_score_overrides == {}
