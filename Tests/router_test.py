import pytest
import router

'''
Test all valid arguments - operation system, browser and algorithm combinations to get the right container key
'''


@pytest.mark.choose_container_function
def test_linux_chrome_nonpqc_key():
    key = router.choose_container("linux", "chrome", "non-pqc")  # non-pqc navigates to kyber
    assert key == "linux_chrome_kyber", "Error with key linux_chrome_non-pqc"


def test_linux_chrome_kyber_key():
    key = router.choose_container("linux", "chrome", "kyber")
    assert key == "linux_chrome_kyber", "Error with key linux_chrome_kyber"


def test_linux_chrome_mlkem_key():
    key = router.choose_container("linux", "chrome", "mlkem")
    assert key == "linux_chrome_mlkem", "Error with key linux_chrome_mlkem"


def test_windows_chrome_nonpqc_key():
    key = router.choose_container("windows", "chrome", "non-pqc")  # non-pqc navigates to kyber
    assert key == "windows_chrome_kyber", "Error with key windows_chrome_non-pqc"


def test_windows_chrome_kyber_key():
    key = router.choose_container("windows", "chrome", "kyber")
    assert key == "windows_chrome_kyber", "Error with key windows_chrome_kyber"


def test_windows_chrome_mlkem_key():
    key = router.choose_container("windows", "chrome", "mlkem")
    assert key == "windows_chrome_mlkem", "Error with key windows_chrome_mlkem"


def test_macos_chrome_nonpqc_key():
    key = router.choose_container("macos", "chrome", "non-pqc")  # non-pqc navigates to kyber
    assert key == "macos_chrome_kyber", "Error with key macos_chrome_non-pqc"


def test_macos_chrome_kyber_key():
    key = router.choose_container("macos", "chrome", "kyber")
    assert key == "macos_chrome_kyber", "Error with key macos_chrome_kyber"


def test_macos_chrome_mlkem_key():
    key = router.choose_container("macos", "chrome", "mlkem")
    assert key == "macos_chrome_mlkem", "Error with key macos_chrome_mlkem"


def test_linux_firefox_nonpqc_key():
    key = router.choose_container("linux", "firefox", "non-pqc")  # non-pqc navigates to kyber
    assert key == "linux_firefox_kyber", "Error with key linux_firefox_non-pqc"


def test_linux_firefox_kyber_key():
    key = router.choose_container("linux", "firefox", "kyber")
    assert key == "linux_firefox_kyber", "Error with key linux_firefox_kyber"


def test_linux_firefox_mlkem_key():
    key = router.choose_container("linux", "firefox", "mlkem")
    assert key == "linux_firefox_mlkem", "Error with key linux_firefox_mlkem"


def test_windows_firefox_nonpqc_key():
    key = router.choose_container("windows", "firefox", "non-pqc")  # non-pqc navigates to kyber
    assert key == "windows_firefox_kyber", "Error with key windows_firefox_non-pqc"


def test_windows_firefox_kyber_key():
    key = router.choose_container("windows", "firefox", "kyber")
    assert key == "windows_firefox_kyber", "Error with key windows_firefox_kyber"


def test_windows_firefox_mlkem_key():
    key = router.choose_container("windows", "firefox", "mlkem")
    assert key == "windows_firefox_mlkem", "Error with key windows_firefox_mlkem"


def test_macos_firefox_nonpqc_key():
    key = router.choose_container("macos", "firefox", "non-pqc")  # non-pqc navigates to kyber
    assert key == "macos_firefox_kyber", "Error with key macos_firefox_non-pqc"


def test_macos_firefox_kyber_key():
    key = router.choose_container("macos", "firefox", "kyber")
    assert key == "macos_firefox_kyber", "Error with key macos_firefox_kyber"


def test_macos_firefox_mlkem_key():
    key = router.choose_container("macos", "firefox", "mlkem")
    assert key == "macos_firefox_mlkem", "Error with key macos_firefox_mlkem"


'''
Test invalid arguments to get errors and exceptions
'''


def test_invalid_os():
    with pytest.raises(ValueError):
        router.choose_container("invalid", "chrome", "non-pqc")


def test_invalid_browser():
    with pytest.raises(ValueError):
        router.choose_container("windows", "invalid", "kyber")


def test_invalid_algorithm():
    with pytest.raises(ValueError):
        router.choose_container("macos", "firefox", "invalid")