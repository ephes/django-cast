#!/bin/zsh

cat .env | while read line
do
    if [[ ($line != '#'*) && (! -z $line) ]]
    then
        echo $line
        # export $line ## does not work dunno why
    fi
done
