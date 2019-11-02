branch=$(git branch | sed -n -e 's/^\* \(.*\)/\1/p')
if [ $branch != "release" ]
then
	echo "Must be in release branch"
	exit
fi

git merge origin/master --no-edit
rm server/static/app-dev.js
rm server/static/app.js
cd client/
lein clean
lein cljsbuild once release

cd ../server/style/
bundle exec compass clean
bundle exec compass compile

cd ../..
git add server/static
git add server/style/js
git commit -m "update static"
git push origin release -f

cd devops/
ansible-playbook ansible/deploy.yml -i ansible/prod

cd ..
