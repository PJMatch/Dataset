source .env

make_backup(){
    ssh -t ${SSH_USER}@${SSH_HOST} "
    if mountpoint -q /pjm; then
        echo 'Dysk /pjm jest już otwarty'
    else
        sudo cryptsetup luksOpen /dev/sda pjm    
        sudo mount /dev/mapper/pjm /pjm 
    fi

    if mountpoint -q /pjm; then
        rsync -av --delete /pjm/baza_wideo/ /pjm/baza_wideo_backup/

        sudo umount /pjm
        sudo cryptsetup luksClose /dev/mapper/pjm
        echo "Pomyslne zrobiono backup pilkow"
    else
        echo 'Dysk nie zostal zamontowany'
    fi
    "
}

make_backup