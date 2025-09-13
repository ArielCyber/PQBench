import pytest
from switcher import switcher

'''
Test all valid arguments - operation system, browser and algorithm combinations to get the right container key
'''


@pytest.mark.choose_container_function
def test_linux_chrome_nonpqc_key():
    key = switcher.choose_container("linux", "non-pqc")  # non-pqc navigates to kyber
    assert key == "linux_kyber", "Error with key linux_chrome_non-pqc"


def test_linux_chrome_kyber_key():
    key = switcher.choose_container("linux", "kyber")
    assert key == "linux_kyber", "Error with key linux_chrome_kyber"


def test_linux_chrome_mlkem_key():
    key = switcher.choose_container("linux", "mlkem")
    assert key == "linux_mlkem", "Error with key linux_chrome_mlkem"


def test_windows_chrome_nonpqc_key():
    key = switcher.choose_container("windows", "non-pqc")  # non-pqc navigates to kyber
    assert key == "windows_kyber", "Error with key windows_chrome_non-pqc"


def test_windows_chrome_kyber_key():
    key = switcher.choose_container("windows", "kyber")
    assert key == "windows_kyber", "Error with key windows_chrome_kyber"


def test_windows_chrome_mlkem_key():
    key = switcher.choose_container("windows", "mlkem")
    assert key == "windows_mlkem", "Error with key windows_chrome_mlkem"


def test_macos_chrome_nonpqc_key():
    key = switcher.choose_container("macos", "non-pqc")  # non-pqc navigates to kyber
    assert key == "macos_kyber", "Error with key macos_chrome_non-pqc"


def test_macos_chrome_kyber_key():
    key = switcher.choose_container("macos", "kyber")
    assert key == "macos_kyber", "Error with key macos_chrome_kyber"


def test_macos_chrome_mlkem_key():
    key = switcher.choose_container("macos", "mlkem")
    assert key == "macos_mlkem", "Error with key macos_chrome_mlkem"


def test_linux_firefox_nonpqc_key():
    key = switcher.choose_container("linux", "non-pqc")  # non-pqc navigates to kyber
    assert key == "linux_kyber", "Error with key linux_firefox_non-pqc"


def test_linux_firefox_kyber_key():
    key = switcher.choose_container("linux", "kyber")
    assert key == "linux_kyber", "Error with key linux_firefox_kyber"


def test_linux_firefox_mlkem_key():
    key = switcher.choose_container("linux", "mlkem")
    assert key == "linux_mlkem", "Error with key linux_firefox_mlkem"


def test_windows_firefox_nonpqc_key():
    key = switcher.choose_container("windows", "non-pqc")  # non-pqc navigates to kyber
    assert key == "windows_kyber", "Error with key windows_firefox_non-pqc"


def test_windows_firefox_kyber_key():
    key = switcher.choose_container("windows", "kyber")
    assert key == "windows_kyber", "Error with key windows_firefox_kyber"


def test_windows_firefox_mlkem_key():
    key = switcher.choose_container("windows", "mlkem")
    assert key == "windows_mlkem", "Error with key windows_firefox_mlkem"


def test_macos_firefox_nonpqc_key():
    key = switcher.choose_container("macos", "non-pqc")  # non-pqc navigates to kyber
    assert key == "macos_kyber", "Error with key macos_firefox_non-pqc"


def test_macos_firefox_kyber_key():
    key = switcher.choose_container("macos", "kyber")
    assert key == "macos_kyber", "Error with key macos_firefox_kyber"


def test_macos_firefox_mlkem_key():
    key = switcher.choose_container("macos", "mlkem")
    assert key == "macos_mlkem", "Error with key macos_firefox_mlkem"


'''
Test invalid arguments to get errors and exceptions
'''


def test_invalid_os():
    with pytest.raises(ValueError):
        switcher.choose_container("invalid", "non-pqc")


def test_invalid_algorithm():
    with pytest.raises(ValueError):
        switcher.choose_container("macos", "invalid")